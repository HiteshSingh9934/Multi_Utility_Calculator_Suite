"""finance-service: the business and finance tools.

    GET  /gst/rates  current GST slabs (the UI builds its rate buttons from this)
    POST /gst        {"amount": 1000, "rate": 18, "mode": "exclusive", "supply": "intra"}
    POST /emi        {"principal": 500000, "annual_rate": 9, "tenure": 5, "tenure_unit": "years"}
    GET  /health

Money is calculated with Decimal and rounded to the paisa, so CGST + SGST
always adds up to the GST amount exactly.
"""
import math
import os
import signal
import socket
import threading
import time
from decimal import ROUND_HALF_UP, Decimal

import requests
from flask import Flask, Response, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from werkzeug.exceptions import HTTPException

SERVICE = "finance-service"
VERSION = "3.2.0"
HOSTNAME = socket.gethostname()  # container ID under Docker, pod name under Kubernetes
HISTORY_URL = os.environ.get("HISTORY_URL", "http://history-service:5000").rstrip("/")

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Shared helpers (every microservice keeps its own copy, so each one can be
# built, deployed and scaled on its own)
# ---------------------------------------------------------------------------

class BadInput(Exception):
    """Something the caller can fix. Becomes a 400 response."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.message = message
        self.field = field


@app.errorhandler(BadInput)
def handle_bad_input(err):
    body = {"error": err.message}
    if err.field:
        body["field"] = err.field
    return jsonify(body), 400


@app.errorhandler(HTTPException)
def handle_http_error(err):
    return jsonify(error=err.description), err.code


@app.errorhandler(Exception)
def handle_unexpected_error(err):
    app.logger.exception("Unhandled error")
    return jsonify(error=f"Something went wrong in {SERVICE}"), 500




# ---------------------------------------------------------------------------
# Prometheus metrics (scraped from /metrics by the monitoring profile)
# ---------------------------------------------------------------------------

REQUESTS = Counter("http_requests_total", "HTTP requests handled", ["service", "method", "endpoint", "status"])
LATENCY = Histogram("http_request_duration_seconds", "Time taken to handle a request", ["service", "endpoint"],
                    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))
UNTRACKED = {"/health", "/ready", "/metrics"}


@app.before_request
def start_timer():
    g.started = time.perf_counter()


@app.after_request
def finish_request(response):
    response.headers["X-Served-By"] = HOSTNAME
    endpoint = request.url_rule.rule if request.url_rule else "unmatched"
    if endpoint not in UNTRACKED:
        LATENCY.labels(SERVICE, endpoint).observe(time.perf_counter() - g.get("started", time.perf_counter()))
        REQUESTS.labels(SERVICE, request.method, endpoint, str(response.status_code)).inc()
    return response


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadInput("Send the inputs as a JSON object")
    return data


def read_number(data, field, label, minimum=None, maximum=None, positive=False):
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise BadInput(f"{label} is required", field)
    if isinstance(value, bool):
        raise BadInput(f"{label} must be a number", field)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise BadInput(f"{label} must be a number", field) from None
    if not math.isfinite(number):
        raise BadInput(f"{label} must be a finite number", field)
    if positive and number <= 0:
        raise BadInput(f"{label} must be more than 0", field)
    if minimum is not None and number < minimum:
        raise BadInput(f"{label} must be at least {fmt(minimum)}", field)
    if maximum is not None and number > maximum:
        raise BadInput(f"{label} can't be more than {fmt(maximum)}", field)
    return number


def read_choice(data, field, label, choices, default):
    value = str(data.get(field, default)).strip().lower()
    if value not in choices:
        raise BadInput(f"{label} must be one of: " + ", ".join(choices), field)
    return value


def group_indian(digits):
    """'1234567' -> '12,34,567' (Indian digit grouping)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ",".join(pairs) + "," + tail


def fmt(value, decimals=6):
    """Readable number for history summaries."""
    if value == 0:
        return "0"
    if abs(value) >= 1e15 or abs(value) < 10 ** -decimals:
        return f"{value:.6g}"
    text = f"{abs(value):.{decimals}f}".rstrip("0").rstrip(".")
    if text in ("", "0"):
        return "0"
    whole, _, fraction = text.partition(".")
    sign = "-" if value < 0 else ""
    return sign + group_indian(whole) + (f".{fraction}" if fraction else "")


def save_history(tool, summary, inputs, result):
    """Best effort: if history-service is down, the calculation still succeeds."""
    payload = {
        "tool": tool,
        "service": SERVICE,
        "summary": summary,
        "input": inputs,
        "result": result,
        "served_by": HOSTNAME,
    }
    try:
        response = requests.post(f"{HISTORY_URL}/records", json=payload, timeout=(0.5, 2))
        return response.status_code == 201
    except requests.RequestException as exc:
        app.logger.warning("History not saved: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Chaos lab: break this service on purpose, to watch Docker and Kubernetes recover it
# (every microservice keeps its own copy of this block)
#
#   POST /chaos {"mode": "crash"}                  the process stops; Docker or Kubernetes starts it again
#   POST /chaos {"mode": "slow", "seconds": 30}    every request takes 2.5 s longer, for 30 s
#   POST /chaos {"mode": "errors", "seconds": 30}  every request fails with HTTP 500, for 30 s
#   POST /chaos {"mode": "heal"}                   back to normal at once
#   GET  /chaos                                    what is switched on right now
#
# It only works when CHAOS_ENABLED=true (.env and k8s/01-config.yaml switch it on for the demo).
# /health, /ready and /metrics are never disturbed, so the checks keep telling the truth.
# ---------------------------------------------------------------------------

CHAOS_ENABLED = os.environ.get("CHAOS_ENABLED", "false").strip().lower() in ("1", "true", "yes")
CHAOS_SLOW_SECONDS = 2.5
CHAOS_MODES = ("crash", "slow", "errors", "heal")
CHAOS_FREE = {"/health", "/ready", "/metrics", "/chaos"}
STARTED = time.time()
_chaos = {"mode": None, "until": 0.0}
CHAOS_EVENTS = Counter("chaos_injections_total", "Faults injected by the chaos lab", ["service", "mode"])


def chaos_state():
    """The fault that is switched on right now, or None."""
    left = _chaos["until"] - time.time()
    if _chaos["mode"] and left > 0:
        return {"mode": _chaos["mode"], "seconds_left": round(left)}
    return None


def health_extras():
    """Added to /health: a restarted process shows a small uptime, which is how the lab sees a recovery."""
    return {"uptime_seconds": round(time.time() - STARTED), "chaos": chaos_state()}


def stop_this_process(server):
    """gunicorn: stop its master process, so the container ends and Docker or Kubernetes restarts it."""
    if server.startswith("gunicorn"):
        os.kill(os.getppid(), signal.SIGTERM)
    elif server.startswith("Werkzeug"):        # flask run / python app.py during development
        os._exit(1)
    # anything else (the unit tests) only pretends


@app.before_request
def apply_chaos():
    if not CHAOS_ENABLED or request.path in CHAOS_FREE:
        return None
    state = chaos_state()
    if state and state["mode"] == "slow":
        time.sleep(CHAOS_SLOW_SECONDS)
    elif state and state["mode"] == "errors":
        return jsonify(error=f"{SERVICE} is failing on purpose (chaos lab)", code="chaos"), 500
    return None


@app.route("/chaos", methods=["GET", "POST"])
def chaos():
    if not CHAOS_ENABLED:
        return jsonify(error="The chaos lab is switched off. Set CHAOS_ENABLED=true to use it.",
                       code="chaos_disabled"), 404
    if request.method == "GET":
        return jsonify(service=SERVICE, served_by=HOSTNAME, **health_extras())

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadInput("Send the inputs as a JSON object")
    mode = str(data.get("mode", "")).strip().lower()
    if mode not in CHAOS_MODES:
        raise BadInput("Choose one of: " + ", ".join(CHAOS_MODES), "mode")
    try:
        seconds = int(data.get("seconds", 30))
    except (TypeError, ValueError):
        raise BadInput("Seconds must be a whole number", "seconds") from None
    if not 5 <= seconds <= 120:
        raise BadInput("Seconds must be between 5 and 120", "seconds")

    CHAOS_EVENTS.labels(SERVICE, mode).inc()
    app.logger.warning("Chaos lab: %s on %s", mode, HOSTNAME)
    if mode == "heal":
        _chaos.update(mode=None, until=0.0)
        return jsonify(service=SERVICE, served_by=HOSTNAME, mode=mode, message="Back to normal")
    if mode == "crash":
        threading.Timer(0.5, stop_this_process, args=(request.environ.get("SERVER_SOFTWARE", ""),)).start()
        return jsonify(service=SERVICE, served_by=HOSTNAME, mode=mode,
                       message="This process stops in half a second"), 202
    _chaos.update(mode=mode, until=time.time() + seconds)
    return jsonify(service=SERVICE, served_by=HOSTNAME, mode=mode, seconds=seconds,
                   message=f"{mode} for {seconds} seconds")


@app.get("/health")
def health():
    return jsonify(service=SERVICE, status="ok", version=VERSION, served_by=HOSTNAME, **health_extras())


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------

PAISA = Decimal("0.01")


def to_decimal(number):
    return Decimal(repr(number))  # repr keeps 1000.1 as exactly 1000.1


def money(value):
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


def inr(value, drop_zero_paise=False):
    """Decimal -> '₹1,23,456.78' (or '₹5,00,000' for a round amount when asked)"""
    value = money(value)
    sign = "-" if value < 0 else ""
    whole, _, paise = f"{abs(value):.2f}".partition(".")
    if drop_zero_paise and paise == "00":
        return f"{sign}₹{group_indian(whole)}"
    return f"{sign}₹{group_indian(whole)}.{paise}"


def percent_text(value):
    """Decimal('18') -> '18', Decimal('0.250') -> '0.25'"""
    text = f"{value.normalize():f}"
    return text


# ---------------------------------------------------------------------------
# GST
# ---------------------------------------------------------------------------

GST_SLABS = [
    {"rate": 5, "label": "5%", "description": "Everyday essentials such as packaged food items and fertilisers"},
    {"rate": 18, "label": "18%", "description": "Standard rate for most goods and services"},
    {"rate": 40, "label": "40%", "description": "Luxury and sin goods such as large cars, aerated drinks and tobacco"},
    {"rate": 3, "label": "3%", "description": "Gold, silver and jewellery"},
    {"rate": 0.25, "label": "0.25%", "description": "Rough diamonds and precious stones"},
    {"rate": 0, "label": "0%", "description": "Nil-rated items such as fresh produce and milk"},
]


@app.get("/gst/rates")
def gst_rates():
    return jsonify(
        slabs=GST_SLABS,
        note="Slabs in force since the GST reform of 22 September 2025",
    )


@app.post("/gst")
def gst():
    data = json_body()
    amount = to_decimal(read_number(data, "amount", "Amount", maximum=1e12, positive=True))
    rate = to_decimal(read_number(data, "rate", "GST rate", minimum=0, maximum=100))
    # exclusive: the amount is before GST (add GST)
    # inclusive: the amount already includes GST (take GST out)
    mode = read_choice(data, "mode", "Mode", ("exclusive", "inclusive"), "exclusive")
    # intra: sale within one state, split into CGST + SGST
    # inter: sale between states, charged as IGST
    supply = read_choice(data, "supply", "Supply type", ("intra", "inter"), "intra")

    if mode == "exclusive":
        net = money(amount)
        tax = money(net * rate / 100)
        gross = net + tax
    else:
        gross = money(amount)
        net = money(gross * 100 / (100 + rate))
        tax = gross - net

    if supply == "intra":
        cgst = money(tax / 2)
        sgst = tax - cgst  # takes the leftover paisa, so the two halves always add up
        half_rate = rate / 2
        breakdown = [
            {"label": "CGST", "rate": float(half_rate), "amount": float(cgst)},
            {"label": "SGST", "rate": float(half_rate), "amount": float(sgst)},
        ]
    else:
        breakdown = [{"label": "IGST", "rate": float(rate), "amount": float(tax)}]

    rate_text = percent_text(rate)
    if mode == "exclusive":
        summary = f"{rate_text}% GST on {inr(net)}: GST {inr(tax)}, total {inr(gross)}"
    else:
        summary = f"{inr(gross)} including {rate_text}% GST: price {inr(net)}, GST {inr(tax)}"

    result = {
        "mode": mode,
        "supply": supply,
        "rate": float(rate),
        "net_amount": float(net),
        "gst_amount": float(tax),
        "gross_amount": float(gross),
        "breakdown": breakdown,
        "summary": summary,
    }
    result["saved"] = save_history(
        "gst",
        summary,
        {"amount": float(amount), "rate": float(rate), "mode": mode, "supply": supply},
        {"net_amount": float(net), "gst_amount": float(tax), "gross_amount": float(gross)},
    )
    result["served_by"] = HOSTNAME
    return jsonify(result)


# ---------------------------------------------------------------------------
# EMI (equated monthly instalment)
# ---------------------------------------------------------------------------

MAX_MONTHS = 480  # 40 years


def tenure_text(months):
    years, rest = divmod(months, 12)
    parts = []
    if years:
        parts.append(f"{years} year" + ("s" if years != 1 else ""))
    if rest:
        parts.append(f"{rest} month" + ("s" if rest != 1 else ""))
    return " ".join(parts)


def amortise(principal, annual_rate, months):
    """Monthly EMI, plus how each payment splits into interest and principal."""
    r = annual_rate / 12 / 100
    if r == 0:
        emi = principal / months
    else:
        growth = (1 + r) ** months
        emi = principal * r * growth / (growth - 1)

    balance = principal
    total_interest = 0.0
    yearly, monthly = [], []
    year_principal = year_interest = 0.0
    for month in range(1, months + 1):
        interest = balance * r
        principal_part = emi - interest
        if month == months:
            principal_part = balance  # absorb rounding so the loan closes at exactly 0
        balance = max(balance - principal_part, 0.0)
        total_interest += interest
        year_principal += principal_part
        year_interest += interest
        monthly.append({
            "month": month,
            "principal": round(principal_part, 2),
            "interest": round(interest, 2),
            "balance": round(balance, 2),
        })
        if month % 12 == 0 or month == months:
            yearly.append({
                "year": (month - 1) // 12 + 1,
                "principal": round(year_principal, 2),
                "interest": round(year_interest, 2),
                "balance": round(balance, 2),
            })
            year_principal = year_interest = 0.0
    return emi, total_interest, yearly, monthly


@app.post("/emi")
def emi():
    data = json_body()
    principal = read_number(data, "principal", "Loan amount", maximum=1e11, positive=True)
    annual_rate = read_number(data, "annual_rate", "Interest rate", minimum=0, maximum=50)
    tenure = read_number(data, "tenure", "Tenure", positive=True)
    unit = read_choice(data, "tenure_unit", "Tenure unit", ("years", "months"), "years")

    months = tenure * 12 if unit == "years" else tenure
    if abs(months - round(months)) > 1e-9:
        raise BadInput("Tenure must work out to a whole number of months", "tenure")
    months = int(round(months))
    if months > MAX_MONTHS:
        raise BadInput("Tenure can't be more than 40 years (480 months)", "tenure")

    emi_amount, total_interest, yearly, monthly = amortise(principal, annual_rate, months)
    total_payment = principal + total_interest
    summary = (
        f"EMI {inr(to_decimal(emi_amount))} a month for a {inr(to_decimal(principal), drop_zero_paise=True)} loan "
        f"at {fmt(annual_rate)}% over {tenure_text(months)}"
    )

    result = {
        "principal": round(principal, 2),
        "annual_rate": annual_rate,
        "months": months,
        "tenure_text": tenure_text(months),
        "emi": round(emi_amount, 2),
        "total_interest": round(total_interest, 2),
        "total_payment": round(total_payment, 2),
        "interest_share": round(total_interest / total_payment * 100, 2),
        "yearly": yearly,
        "summary": summary,
    }
    if data.get("include_monthly"):
        result["monthly"] = monthly
    result["saved"] = save_history(
        "emi",
        summary,
        {"principal": principal, "annual_rate": annual_rate, "months": months},
        {"emi": result["emi"], "total_interest": result["total_interest"],
         "total_payment": result["total_payment"]},
    )
    result["served_by"] = HOSTNAME
    return jsonify(result)


if __name__ == "__main__":  # local development only; containers run gunicorn
    app.run(host="0.0.0.0", port=5000)

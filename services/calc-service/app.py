"""calc-service: the original sum microservice (Task 4), grown into a basic calculator.

    POST /calculate   {"num1": 10, "num2": 5, "operation": "add"}
    GET  /health

Every result is also sent to history-service, which stores it in PostgreSQL.
"""
import math
import os
import signal
import socket
import threading
import time

import requests
from flask import Flask, Response, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from werkzeug.exceptions import HTTPException

SERVICE = "calc-service"
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


def clean(value):
    """Drop floating-point noise: 0.1 + 0.2 gives 0.3, not 0.30000000000000004."""
    return float(f"{value:.12g}")


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
# Calculator
# ---------------------------------------------------------------------------

OPERATIONS = {
    "add": "+",
    "subtract": "−",
    "multiply": "×",
    "divide": "÷",
    "power": "^",
    "modulus": "mod",
    "percent_of": "% of",
}


def compute(a, b, operation):
    if operation == "add":
        return a + b
    if operation == "subtract":
        return a - b
    if operation == "multiply":
        return a * b
    if operation in ("divide", "modulus") and b == 0:
        raise BadInput("Cannot divide by zero", "num2")
    if operation == "divide":
        return a / b
    if operation == "modulus":
        return math.fmod(a, b)  # remainder keeps the sign of num1, like most calculators
    if operation == "percent_of":
        return a / 100 * b
    if operation == "power":
        try:
            result = a ** b
        except OverflowError:
            raise BadInput("The result is too large to calculate") from None
        except ZeroDivisionError:
            raise BadInput("Zero can't be raised to a negative power", "num2") from None
        if isinstance(result, complex):
            raise BadInput("A negative number can't be raised to a fractional power", "num2")
        return result
    raise BadInput("Choose one of: " + ", ".join(OPERATIONS), "operation")


@app.post("/calculate")
def calculate():
    data = json_body()
    a = read_number(data, "num1", "First number")
    b = read_number(data, "num2", "Second number")
    operation = str(data.get("operation", "")).strip().lower()
    if operation not in OPERATIONS:
        raise BadInput("Choose one of: " + ", ".join(OPERATIONS), "operation")

    result = compute(a, b, operation)
    if not math.isfinite(result):
        raise BadInput("The result is too large to calculate")
    result = clean(result)

    symbol = OPERATIONS[operation]
    if operation == "percent_of":
        expression = f"{fmt(a)}% of {fmt(b)} = {fmt(result)}"
    else:
        expression = f"{fmt(a)} {symbol} {fmt(b)} = {fmt(result)}"

    saved = save_history(
        "calculator",
        expression,
        {"num1": a, "num2": b, "operation": operation},
        {"result": result},
    )
    return jsonify(
        num1=a,
        num2=b,
        operation=operation,
        symbol=symbol,
        result=result,
        expression=expression,
        saved=saved,
        served_by=HOSTNAME,
    )


if __name__ == "__main__":  # local development only; containers run gunicorn
    app.run(host="0.0.0.0", port=5000)

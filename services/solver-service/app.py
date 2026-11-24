"""solver-service: worked solutions, and questions in plain English.

    POST /ask            {"text": "EMI for 5 lakh at 9% for 3 years"}
    POST /derivative     {"expression": "x^2 sin(x)", "at": 2}
    POST /integral       {"expression": "x e^x", "lower": 0, "upper": 2}
    POST /equation       {"equation": "x^2 - 5x + 6 = 0"}
    POST /matrix-steps   {"operation": "inverse", "matrix": [[2, 1], [5, 3]]}
    POST /emi-steps      {"principal": 500000, "annual_rate": 9, "tenure": 3, "tenure_unit": "years"}
    POST /gst-steps      {"amount": 2499, "rate": 18, "mode": "exclusive"}
    GET  /examples
    GET  /health

Every answer comes with the working, step by step. /ask reads a sentence, then calls the other
microservices (finance, converter, calc, math) when they hold the answer.
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

import asking
import calculus_steps

SERVICE = "solver-service"
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
# Talking to the other microservices
# ---------------------------------------------------------------------------

SERVICE_NAMES = {"calc": "calc-service", "converter": "converter-service", "finance": "finance-service",
                 "math": "math-service"}


class Backend:
    """How /ask reaches the other services. Inside Docker or Kubernetes their names are their addresses."""

    def call(self, key, path, payload=None, method="POST"):
        name = SERVICE_NAMES[key]
        base = os.environ.get(f"{key.upper()}_URL", f"http://{name}:5000").rstrip("/")
        try:
            response = requests.request(method, base + path, json=payload if method == "POST" else None, timeout=(1, 6))
        except requests.RequestException as exc:
            app.logger.warning("%s did not answer: %s", name, exc)
            raise asking.ServiceProblem(name, f"{name} isn't answering right now") from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 500:
            raise asking.ServiceProblem(name, f"{name} isn't answering right now", response.status_code)
        if response.status_code >= 400:
            raise calculus_steps.Unsupported(body.get("error") or f"{name} could not use that input")
        return body, body.get("served_by")


BACKEND = Backend()


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------

@app.errorhandler(calculus_steps.Unsupported)
def handle_unsupported(err):
    return jsonify(error=str(err), code="cannot_solve"), 422


@app.errorhandler(asking.NotUnderstood)
def handle_not_understood(err):
    return jsonify(error=str(err), code="not_understood", examples=asking.EXAMPLES[:6]), 422


@app.errorhandler(asking.ServiceProblem)
def handle_service_problem(err):
    return jsonify(error=err.message, code="service_unavailable", service=err.service), 503


def finish(result):
    """Save the answer when this service produced it, and add who answered."""
    record = result.pop("record", None)
    saved = None        # nothing to save here (the EMI and GST tools save their own result): not a failure
    if record:
        saved = save_history(record["tool"], record["summary"], record["input"], record["result"])
    result["saved"] = saved
    result["used"] = [{"service": SERVICE, "served_by": HOSTNAME}] + result.get("used", [])
    result["served_by"] = HOSTNAME
    return jsonify(result)


def text_field(data, field, label):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BadInput(f"Enter {label}", field)
    if len(value) > asking.expr.MAX_LENGTH:
        raise BadInput(f"{label[0].upper() + label[1:]} is too long", field)
    return value.strip()


def optional_text(data, field):
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise BadInput("Use a number or an expression such as pi/2", field)
    return str(value).strip()


@app.post("/ask")
def ask():
    data = json_body()
    question = data.get("text")
    if not isinstance(question, str):
        raise BadInput("Type a question", "text")
    result = asking.answer_question(question, BACKEND)
    if result.get("record"):
        result["record"]["input"]["question"] = question.strip()   # so a history click can ask it again
    return finish(result)


@app.get("/examples")
def examples():
    return jsonify(examples=asking.EXAMPLES, served_by=HOSTNAME)


@app.post("/derivative")
def derivative():
    data = json_body()
    return finish(asking.derivative_result(text_field(data, "expression", "a function"), optional_text(data, "at")))


@app.post("/integral")
def integral():
    data = json_body()
    return finish(asking.integral_result(text_field(data, "expression", "a function"),
                                         optional_text(data, "lower"), optional_text(data, "upper")))


@app.post("/equation")
def equation():
    data = json_body()
    return finish(asking.equation_result(text_field(data, "equation", "an equation")))


@app.post("/matrix-steps")
def matrix_steps():
    data = json_body()
    operation = str(data.get("operation", "")).strip().lower()
    if operation not in ("determinant", "inverse", "rref", "solve"):
        raise BadInput("Choose one of: determinant, inverse, rref, solve", "operation")
    answer, details, steps, understood, resulting = asking.matrix_result(operation, data.get("matrix"), data.get("constants"))
    result = {"intent": operation, "understood": understood, "answer": answer, "details": details, "steps": steps,
              "matrix": resulting,
              "record": {"tool": "solver", "summary": f"{understood}: {answer}",
                         "input": {"kind": "matrix", "operation": operation, "matrix": data.get("matrix")},
                         "result": {"answer": answer}}}
    return finish(result)


@app.post("/emi-steps")
def emi_steps():
    data = json_body()
    principal = read_number(data, "principal", "Loan amount", maximum=1e11, positive=True)
    rate = read_number(data, "annual_rate", "Interest rate", minimum=0, maximum=50)
    tenure = read_number(data, "tenure", "Tenure", positive=True)
    unit = str(data.get("tenure_unit", "years")).strip().lower()
    if unit not in ("years", "months"):
        raise BadInput("Tenure unit must be years or months", "tenure_unit")
    return finish(asking.emi_result(principal, rate, tenure, unit, BACKEND))


@app.post("/gst-steps")
def gst_steps():
    data = json_body()
    amount = read_number(data, "amount", "Amount", maximum=1e12, positive=True)
    rate = read_number(data, "rate", "GST rate", minimum=0, maximum=100)
    mode = str(data.get("mode", "exclusive")).strip().lower()
    if mode not in ("exclusive", "inclusive"):
        raise BadInput("Mode must be exclusive or inclusive", "mode")
    return finish(asking.gst_result(amount, rate, mode, BACKEND, []))


if __name__ == "__main__":  # local development only; containers run gunicorn
    app.run(host="0.0.0.0", port=5000)

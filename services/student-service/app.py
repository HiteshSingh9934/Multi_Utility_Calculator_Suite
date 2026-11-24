"""student-service: tools for students.

    GET  /formulas     CGPA formulas and the grading scale (the UI builds its menus from this)
    POST /cgpa         {"direction": "to_percentage", "value": 8.2, "formula": "mitadt"}
    POST /grades       {"subjects": [{"name": "Maths", "marks": 78, "max_marks": 100, "credits": 4}]}
    POST /attendance   {"attended": 42, "total": 60, "required": 75}
    GET  /health
"""
import math
import os
import signal
import socket
import threading
import time
from fractions import Fraction

import requests
from flask import Flask, Response, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from werkzeug.exceptions import HTTPException

SERVICE = "student-service"
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


def read_whole_number(data, field, label, minimum=None, maximum=None):
    number = read_number(data, field, label, minimum=minimum, maximum=maximum)
    if number != int(number):
        raise BadInput(f"{label} must be a whole number", field)
    return int(number)


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
# CGPA <-> percentage. Every formula has the form: percentage = multiplier × CGPA + offset
# ---------------------------------------------------------------------------

CGPA_FORMULAS = [
    {"id": "mitadt", "name": "MIT ADT University", "formula": "CGPA × 9.56", "multiplier": 9.56, "offset": 0},
    {"id": "cbse", "name": "CBSE", "formula": "CGPA × 9.5", "multiplier": 9.5, "offset": 0},
    {"id": "x10", "name": "Straight", "formula": "CGPA × 10", "multiplier": 10, "offset": 0},
    {"id": "minus075", "name": "Less 0.75", "formula": "(CGPA − 0.75) × 10", "multiplier": 10, "offset": -7.5},
    {"id": "custom", "name": "Custom", "formula": "CGPA × multiplier + offset", "multiplier": None, "offset": None},
]
FORMULAS_BY_ID = {f["id"]: f for f in CGPA_FORMULAS}


@app.post("/cgpa")
def cgpa():
    data = json_body()
    direction = str(data.get("direction", "to_percentage")).strip().lower()
    if direction not in ("to_percentage", "to_cgpa"):
        raise BadInput("Direction must be to_percentage or to_cgpa", "direction")
    formula_id = str(data.get("formula", "mitadt")).strip().lower()
    if formula_id not in FORMULAS_BY_ID:
        raise BadInput("Choose one of: " + ", ".join(FORMULAS_BY_ID), "formula")
    formula = FORMULAS_BY_ID[formula_id]

    if formula_id == "custom":
        multiplier = read_number(data, "multiplier", "Multiplier", maximum=20, positive=True)
        offset = read_number(data, "offset", "Offset", minimum=-50, maximum=50)
        sign = "+" if offset >= 0 else "−"
        formula_text = f"CGPA × {fmt(multiplier)} {sign} {fmt(abs(offset))}" if offset else f"CGPA × {fmt(multiplier)}"
    else:
        multiplier, offset = formula["multiplier"], formula["offset"]
        formula_text = formula["formula"]

    if direction == "to_percentage":
        value = read_number(data, "value", "CGPA", minimum=0, maximum=10)
        raw = multiplier * value + offset
        result = round(min(max(raw, 0), 100), 2)
        summary = f"CGPA {fmt(value)} = {fmt(result)}% ({formula['name']}: {formula_text})"
    else:
        value = read_number(data, "value", "Percentage", minimum=0, maximum=100)
        raw = (value - offset) / multiplier
        result = round(min(max(raw, 0), 10), 2)
        summary = f"{fmt(value)}% = CGPA {fmt(result)} ({formula['name']}: {formula_text})"

    response = {
        "direction": direction,
        "value": value,
        "result": result,
        "formula": formula_id,
        "formula_name": formula["name"],
        "formula_text": formula_text,
        "clamped": round(raw, 2) != result,
        "summary": summary,
    }
    response["saved"] = save_history(
        "cgpa",
        summary,
        {"direction": direction, "value": value, "formula": formula_id,
         "multiplier": multiplier, "offset": offset},
        {"result": result},
    )
    response["served_by"] = HOSTNAME
    return jsonify(response)


# ---------------------------------------------------------------------------
# Marks, average and grades (10-point scale)
# ---------------------------------------------------------------------------

GRADE_SCALE = [  # (minimum %, grade, grade point, meaning)
    (90, "O", 10, "Outstanding"),
    (80, "A+", 9, "Excellent"),
    (70, "A", 8, "Very good"),
    (60, "B+", 7, "Good"),
    (50, "B", 6, "Above average"),
    (45, "C", 5, "Average"),
    (40, "P", 4, "Pass"),
    (0, "F", 0, "Fail"),
]
PASS_PERCENT = 40
MAX_SUBJECTS = 20


def grade_for(percent):
    for minimum, grade, point, meaning in GRADE_SCALE:
        if percent >= minimum:
            return grade, point, meaning
    return "F", 0, "Fail"


@app.get("/formulas")
def formulas():
    return jsonify(
        cgpa_formulas=CGPA_FORMULAS,
        grade_scale=[
            {"min_percent": m, "grade": g, "grade_point": p, "meaning": t} for m, g, p, t in GRADE_SCALE
        ],
        pass_percent=PASS_PERCENT,
    )


@app.post("/grades")
def grades():
    data = json_body()
    subjects = data.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        raise BadInput("Add at least one subject", "subjects")
    if len(subjects) > MAX_SUBJECTS:
        raise BadInput(f"Add at most {MAX_SUBJECTS} subjects", "subjects")

    rows = []
    for index, subject in enumerate(subjects, start=1):
        if not isinstance(subject, dict):
            raise BadInput(f"Subject {index} must be an object", "subjects")
        name = str(subject.get("name") or f"Subject {index}").strip()[:60] or f"Subject {index}"
        max_marks = read_number(subject, "max_marks", f"{name}: maximum marks", maximum=1000, positive=True) \
            if subject.get("max_marks") not in (None, "") else 100.0
        marks = read_number(subject, "marks", f"{name}: marks", minimum=0, maximum=max_marks)
        credits = None
        if subject.get("credits") not in (None, ""):
            credits = read_number(subject, "credits", f"{name}: credits", minimum=0, maximum=20)
        percent = round(marks / max_marks * 100, 2)
        grade, point, meaning = grade_for(percent)
        rows.append({
            "name": name,
            "marks": marks,
            "max_marks": max_marks,
            "percentage": percent,
            "grade": grade,
            "grade_point": point,
            "meaning": meaning,
            "passed": percent >= PASS_PERCENT,
            "credits": credits,
        })

    total = sum(r["marks"] for r in rows)
    total_max = sum(r["max_marks"] for r in rows)
    overall = round(total / total_max * 100, 2)
    overall_grade, overall_point, overall_meaning = grade_for(overall)
    failed = [r["name"] for r in rows if not r["passed"]]

    sgpa = None
    if all(r["credits"] for r in rows):  # every subject has credits above 0
        total_credits = sum(r["credits"] for r in rows)
        sgpa = round(sum(r["credits"] * r["grade_point"] for r in rows) / total_credits, 2)

    summary = f"{len(rows)} subject{'s' if len(rows) != 1 else ''}: {fmt(overall)}%, grade {overall_grade}"
    if sgpa is not None:
        summary += f", SGPA {fmt(sgpa)}"
    if failed:
        summary += f", {len(failed)} below pass mark"

    response = {
        "subjects": rows,
        "total_marks": round(total, 2),
        "total_max": round(total_max, 2),
        "percentage": overall,
        "average_marks": round(total / len(rows), 2),
        "average_percentage": round(sum(r["percentage"] for r in rows) / len(rows), 2),
        "same_max_marks": len({r["max_marks"] for r in rows}) == 1,
        "overall_grade": overall_grade,
        "overall_grade_point": overall_point,
        "overall_meaning": overall_meaning,
        "sgpa": sgpa,
        "passed_count": len(rows) - len(failed),
        "failed_subjects": failed,
        "pass_percent": PASS_PERCENT,
        "summary": summary,
    }
    response["saved"] = save_history(
        "grades",
        summary,
        {"subjects": [{k: r[k] for k in ("name", "marks", "max_marks", "credits")} for r in rows]},
        {"percentage": overall, "grade": overall_grade, "sgpa": sgpa},
    )
    response["served_by"] = HOSTNAME
    return jsonify(response)


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

@app.post("/attendance")
def attendance():
    data = json_body()
    total = read_whole_number(data, "total", "Classes held", minimum=1, maximum=100000)
    attended = read_whole_number(data, "attended", "Classes attended", minimum=0, maximum=total)
    required_number = read_number(data, "required", "Required attendance", maximum=100, positive=True) \
        if data.get("required") not in (None, "") else 75.0

    # Exact fractions, so 75% of 60 classes is exactly 45 (no floating-point surprises)
    required = Fraction(repr(required_number))
    current = Fraction(attended * 100, total)
    can_miss = must_attend = None

    if current >= required:
        # (attended / (total + x)) >= required%  ->  x <= attended*100/required - total
        can_miss = math.floor(attended * 100 / required - total)
        if can_miss == 0:
            message = f"You're right at the limit. Missing the next class takes you below {fmt(required_number)}%."
        else:
            message = (f"You can miss {can_miss} more class{'es' if can_miss != 1 else ''} "
                       f"and stay at or above {fmt(required_number)}%.")
    elif required == 100:
        message = "You can't reach 100% any more, because you've already missed a class."
    else:
        # ((attended + x) / (total + x)) >= required%  ->  x >= (required*total - 100*attended) / (100 - required)
        must_attend = math.ceil((required * total - 100 * attended) / (100 - required))
        message = (f"Attend the next {must_attend} class{'es' if must_attend != 1 else ''} in a row "
                   f"to reach {fmt(required_number)}%.")

    percentage = round(float(current), 2)
    summary = f"{attended}/{total} classes = {fmt(percentage)}% (need {fmt(required_number)}%)"
    response = {
        "attended": attended,
        "total": total,
        "percentage": percentage,
        "required": required_number,
        "meets_requirement": current >= required,
        "can_miss": can_miss,
        "must_attend": must_attend,
        "message": message,
        "summary": summary,
    }
    response["saved"] = save_history(
        "attendance",
        summary,
        {"attended": attended, "total": total, "required": required_number},
        {"percentage": percentage, "can_miss": can_miss, "must_attend": must_attend},
    )
    response["served_by"] = HOSTNAME
    return jsonify(response)


if __name__ == "__main__":  # local development only; containers run gunicorn
    app.run(host="0.0.0.0", port=5000)

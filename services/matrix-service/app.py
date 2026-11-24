"""matrix-service: linear algebra for the Calculator Suite.

    POST /matrix     {"operation": "inverse", "a": [["2", "1"], ["1", "1"]]}
                     operations: add, subtract, multiply, scalar, transpose, determinant,
                     inverse, rank, trace, power, rref, solve, eigen
    POST /vector3d   {"a": [1, 2, 3], "b": [4, 5, 6], "c": [0, 0, 1]}
    GET  /health  /metrics

Matrix arithmetic uses exact fractions: the inverse of [[2, 1], [1, 1]] comes out as
whole numbers, and 1/3 stays 1/3 instead of 0.333333. Eigenvalues use NumPy.
"""
import math
import os
import signal
import socket
import threading
import time
from fractions import Fraction

import numpy as np
import requests
from flask import Flask, Response, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from werkzeug.exceptions import HTTPException

SERVICE = "matrix-service"
VERSION = "3.2.0"
HOSTNAME = socket.gethostname()  # container ID under Docker, pod name under Kubernetes
HISTORY_URL = os.environ.get("HISTORY_URL", "http://history-service:5000").rstrip("/")
MAX_SIZE = 8

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


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadInput("Send the inputs as a JSON object")
    return data


def read_choice(data, field, label, choices, default):
    value = str(data.get(field, default)).strip().lower()
    if value not in choices:
        raise BadInput(f"{label} must be one of: " + ", ".join(choices), field)
    return value


def save_history(tool, summary, inputs, result):
    """Best effort: if history-service is down, the calculation still succeeds."""
    payload = {"tool": tool, "service": SERVICE, "summary": summary[:500], "input": inputs,
               "result": result, "served_by": HOSTNAME}
    try:
        response = requests.post(f"{HISTORY_URL}/records", json=payload, timeout=(0.5, 2))
        return response.status_code == 201
    except requests.RequestException as exc:
        app.logger.warning("History not saved: %s", exc)
        return False


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
# Reading numbers and fractions
# ---------------------------------------------------------------------------

LIMIT = Fraction(10) ** 15


def to_fraction(value, where, field):
    """'3', '-2.5', '1/3', 0.1 -> exact Fraction."""
    if isinstance(value, bool) or value is None:
        raise BadInput(f"Fill in {where}", field)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise BadInput(f"{where} must be a finite number", field)
        number = Fraction(repr(value)) if isinstance(value, float) else Fraction(value)
    else:
        text = str(value).strip().replace("−", "-").replace(" ", "")
        if not text:
            raise BadInput(f"Fill in {where}", field)
        if len(text) > 30:
            raise BadInput(f"{where} is too long", field)
        try:
            number = Fraction(text)
        except ZeroDivisionError:
            raise BadInput(f"{where}: a fraction can't have 0 at the bottom", field) from None
        except ValueError:
            raise BadInput(f"{where}: '{text}' isn't a number or a fraction like 3/4", field) from None
    if abs(number) > LIMIT:
        raise BadInput(f"{where} is too large", field)
    return number


def read_matrix(data, field, label):
    rows = data.get(field)
    if not isinstance(rows, list) or not rows:
        raise BadInput(f"Enter matrix {label}", field)
    if len(rows) > MAX_SIZE:
        raise BadInput(f"Matrix {label} can have at most {MAX_SIZE} rows", field)
    width = None
    matrix = []
    for i, row in enumerate(rows):
        if not isinstance(row, list) or not row:
            raise BadInput(f"Row {i + 1} of matrix {label} is empty", field)
        if width is None:
            width = len(row)
            if width > MAX_SIZE:
                raise BadInput(f"Matrix {label} can have at most {MAX_SIZE} columns", field)
        elif len(row) != width:
            raise BadInput(f"Every row of matrix {label} needs the same number of columns", field)
        matrix.append([to_fraction(v, f"{label} row {i + 1}, column {j + 1}", field) for j, v in enumerate(row)])
    return matrix


def read_scalar(data, field, label):
    if data.get(field) in (None, ""):
        raise BadInput(f"Enter {label}", field)
    return to_fraction(data.get(field), label, field)


# ---------------------------------------------------------------------------
# Exact matrix arithmetic with Fractions
# ---------------------------------------------------------------------------

def shape(m):
    return len(m), len(m[0])


def size_text(m):
    rows, cols = shape(m)
    return f"{rows}×{cols}"


def identity(n):
    return [[Fraction(int(i == j)) for j in range(n)] for i in range(n)]


def add(a, b, sign=1):
    return [[x + sign * y for x, y in zip(ra, rb)] for ra, rb in zip(a, b)]


def multiply(a, b):
    columns = list(zip(*b))
    return [[sum((x * y for x, y in zip(row, col)), Fraction(0)) for col in columns] for row in a]


def transpose(m):
    return [list(col) for col in zip(*m)]


def trace(m):
    return sum((m[i][i] for i in range(len(m))), Fraction(0))


def rref(m):
    """Reduced row echelon form by Gauss-Jordan elimination. Returns (matrix, pivot columns)."""
    a = [row[:] for row in m]
    rows, cols = shape(a)
    pivots = []
    r = 0
    for c in range(cols):
        pivot = next((i for i in range(r, rows) if a[i][c] != 0), None)
        if pivot is None:
            continue
        a[r], a[pivot] = a[pivot], a[r]
        lead = a[r][c]
        a[r] = [v / lead for v in a[r]]
        for i in range(rows):
            if i != r and a[i][c] != 0:
                factor = a[i][c]
                a[i] = [vi - factor * vr for vi, vr in zip(a[i], a[r])]
        pivots.append(c)
        r += 1
        if r == rows:
            break
    return a, pivots


def determinant(m):
    a = [row[:] for row in m]
    n = len(a)
    det = Fraction(1)
    for c in range(n):
        pivot = next((r for r in range(c, n) if a[r][c] != 0), None)
        if pivot is None:
            return Fraction(0)
        if pivot != c:
            a[c], a[pivot] = a[pivot], a[c]
            det = -det
        det *= a[c][c]
        for r in range(c + 1, n):
            factor = a[r][c] / a[c][c]
            if factor:
                a[r] = [x - factor * y for x, y in zip(a[r], a[c])]
    return det


def inverse(m):
    n = len(m)
    augmented = [row + identity_row for row, identity_row in zip(m, identity(n))]
    reduced, pivots = rref(augmented)
    if pivots[:n] != list(range(n)):
        return None
    return [row[n:] for row in reduced]


def power(m, k):
    if k < 0:
        m = inverse(m)
        if m is None:
            return None
        k = -k
    result = identity(len(m))
    base = m
    while k:
        if k & 1:
            result = multiply(result, base)
        base = multiply(base, base)
        k >>= 1
    return result


def characteristic_polynomial(m):
    """Coefficients of det(λI − A) by the Faddeev–LeVerrier method: [1, c1, ..., cn]."""
    n = len(m)
    coefficients = [Fraction(1)]
    current = [[Fraction(0)] * n for _ in range(n)]
    for k in range(1, n + 1):
        current = add(multiply(m, current), [[coefficients[-1] * v for v in row] for row in identity(n)])
        coefficients.append(-trace(multiply(m, current)) / k)
    return coefficients


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def float_text(value):
    if value == 0:
        return "0"
    if abs(value - round(value)) < 1e-9 * max(1.0, abs(value)) and abs(value) < 1e15:
        return str(int(round(value))).replace("-", "−")
    text = f"{value:.6g}"
    if "e" in text:
        mantissa, exponent = text.split("e")
        text = f"{mantissa} × 10^{int(exponent)}"
    return text.replace("-", "−")


def fraction_text(f):
    if f.denominator == 1:
        return str(f.numerator).replace("-", "−") if abs(f.numerator) < 10 ** 15 else float_text(float(f))
    if f.denominator <= 10000 and abs(f.numerator) < 10 ** 12:
        return f"{f.numerator}/{f.denominator}".replace("-", "−")
    return float_text(float(f))


def cell(f):
    try:
        value = float(f)
    except OverflowError:
        value = None
    return {"text": fraction_text(f), "value": value if value is None or math.isfinite(value) else None}


def matrix_out(m):
    return [[cell(v) for v in row] for row in m]


def polynomial_text(coefficients):
    n = len(coefficients) - 1
    parts = []
    for i, c in enumerate(coefficients):
        if c == 0:
            continue
        degree = n - i
        size = abs(c)
        if degree == 0:
            body = fraction_text(size)
        else:
            body = ("" if size == 1 else fraction_text(size)) + ("λ" if degree == 1 else f"λ^{degree}")
        sign = "−" if c < 0 else "+"
        parts.append(body if not parts and c > 0 else (f"−{body}" if not parts else f" {sign} {body}"))
    return "".join(parts) or "0"


def complex_text(z):
    real, imag = z.real, z.imag
    if abs(imag) < 1e-10 * max(1.0, abs(real)):
        return float_text(real)
    imag_text = float_text(abs(imag))
    imag_text = "" if imag_text == "1" else imag_text
    if abs(real) < 1e-12:
        return f"{'−' if imag < 0 else ''}{imag_text}i"
    return f"{float_text(real)} {'−' if imag < 0 else '+'} {imag_text}i"


# ---------------------------------------------------------------------------
# /matrix
# ---------------------------------------------------------------------------

OPERATIONS = ("add", "subtract", "multiply", "scalar", "transpose", "determinant", "inverse",
              "rank", "trace", "power", "rref", "solve", "eigen")
NEEDS_B = {"add", "subtract", "multiply", "solve"}
NEEDS_SQUARE = {"determinant", "inverse", "trace", "power", "eigen"}
NAMES = {"add": "A + B", "subtract": "A − B", "multiply": "A × B", "scalar": "kA", "transpose": "Aᵀ",
         "determinant": "det(A)", "inverse": "A⁻¹", "rank": "rank(A)", "trace": "tr(A)", "power": "Aⁿ",
         "rref": "RREF of A", "solve": "Solve AX = B", "eigen": "Eigenvalues of A"}


def as_text_grid(m):
    return [[fraction_text(v).replace("−", "-") for v in row] for row in m]


@app.post("/matrix")
def matrix():
    data = json_body()
    op = read_choice(data, "operation", "Operation", OPERATIONS, "determinant")
    a = read_matrix(data, "a", "A")
    b = read_matrix(data, "b", "B") if op in NEEDS_B else None
    rows, cols = shape(a)
    if op in NEEDS_SQUARE and rows != cols:
        raise BadInput(f"{NAMES[op]} needs a square matrix, but A is {size_text(a)}", "a")

    result = {"operation": op, "name": NAMES[op]}
    inputs = {"operation": op, "a": as_text_grid(a)}
    if b is not None:
        inputs["b"] = as_text_grid(b)

    if op in ("add", "subtract"):
        if shape(a) != shape(b):
            raise BadInput(f"To {'add' if op == 'add' else 'subtract'} matrices they must be the same size, "
                           f"but A is {size_text(a)} and B is {size_text(b)}", "b")
        out = add(a, b, 1 if op == "add" else -1)
        result.update(result_type="matrix", matrix=matrix_out(out))
        summary = f"{NAMES[op]} for two {size_text(a)} matrices"
    elif op == "multiply":
        if cols != len(b):
            raise BadInput(f"A has {cols} column{'s' if cols != 1 else ''} but B has {len(b)} "
                           f"row{'s' if len(b) != 1 else ''}. To multiply, they must be equal.", "b")
        out = multiply(a, b)
        result.update(result_type="matrix", matrix=matrix_out(out))
        summary = f"A × B: {size_text(a)} × {size_text(b)} = {size_text(out)}"
    elif op == "scalar":
        k = read_scalar(data, "scalar", "the number k")
        inputs["scalar"] = fraction_text(k).replace("−", "-")
        result.update(result_type="matrix", matrix=matrix_out([[k * v for v in row] for row in a]))
        summary = f"{fraction_text(k)} × a {size_text(a)} matrix"
    elif op == "transpose":
        result.update(result_type="matrix", matrix=matrix_out(transpose(a)))
        summary = f"Transpose of a {size_text(a)} matrix"
    elif op == "determinant":
        det = determinant(a)
        result.update(result_type="scalar", value=cell(det))
        summary = f"det(A) = {fraction_text(det)} for a {size_text(a)} matrix"
    elif op == "inverse":
        det = determinant(a)
        if det == 0:
            raise BadInput("A has no inverse because its determinant is 0 (the matrix is singular)", "a")
        result.update(result_type="matrix", matrix=matrix_out(inverse(a)), determinant=cell(det))
        summary = f"Inverse of a {size_text(a)} matrix (det = {fraction_text(det)})"
    elif op == "rank":
        _, pivots = rref(a)
        result.update(result_type="scalar", value=cell(Fraction(len(pivots))))
        summary = f"rank(A) = {len(pivots)} for a {size_text(a)} matrix"
    elif op == "trace":
        value = trace(a)
        result.update(result_type="scalar", value=cell(value))
        summary = f"tr(A) = {fraction_text(value)}"
    elif op == "power":
        raw = data.get("power")
        try:
            k = int(str(raw).strip())
        except (TypeError, ValueError):
            raise BadInput("The power n must be a whole number", "power") from None
        if not -10 <= k <= 20:
            raise BadInput("The power n must be between −10 and 20", "power")
        inputs["power"] = k
        out = power(a, k)
        if out is None:
            raise BadInput("A negative power needs an inverse, and A has none (its determinant is 0)", "power")
        if any(max(abs(v.numerator), v.denominator).bit_length() > 3000 for row in out for v in row):
            raise BadInput("The numbers in the answer are too large to show", "power")
        result.update(result_type="matrix", matrix=matrix_out(out), power=k)
        summary = f"A^{k} for a {size_text(a)} matrix"
    elif op == "rref":
        reduced, pivots = rref(a)
        result.update(result_type="matrix", matrix=matrix_out(reduced), pivots=[p + 1 for p in pivots],
                      rank=len(pivots))
        summary = f"RREF of a {size_text(a)} matrix (rank {len(pivots)})"
    elif op == "solve":
        if len(b) != rows:
            raise BadInput(f"B must have {rows} row{'s' if rows != 1 else ''}, one for each equation", "b")
        augmented = [ra + rb for ra, rb in zip(a, b)]
        reduced, pivots = rref(augmented)
        rank_a = sum(1 for p in pivots if p < cols)
        rank_augmented = len(pivots)
        if rank_a < rank_augmented:
            status, solution = "none", None
            message = "No solution: the equations contradict each other"
        elif rank_a < cols:
            status, solution = "infinite", None
            message = f"Infinitely many solutions: {cols - rank_a} variable{'s' if cols - rank_a != 1 else ''} can take any value"
        else:
            status = "unique"
            solution = [row[cols:] for row in reduced[:cols]]
            message = "One solution"
        result.update(result_type="solve", status=status, message=message,
                      solution=matrix_out(solution) if solution else None,
                      rref=matrix_out(reduced), split=cols, rank_a=rank_a, rank_augmented=rank_augmented)
        summary = f"Solved a system of {rows} equation{'s' if rows != 1 else ''} in {cols} unknown{'s' if cols != 1 else ''}: {message.split(':')[0].lower()}"
    else:  # eigen
        values_np = np.array([[float(v) for v in row] for row in a])
        symmetric = bool(np.allclose(values_np, values_np.T))
        if symmetric:
            values, vectors = np.linalg.eigh(values_np)
        else:
            values, vectors = np.linalg.eig(values_np)
        order = np.lexsort((-np.imag(values), -np.real(values)))
        pairs = []
        for i in order:
            vector = np.asarray(vectors[:, i], dtype=complex)
            biggest = vector[np.argmax(np.abs(vector))]
            if abs(biggest) > 0:
                vector = vector / biggest        # make the largest component 1, e.g. (1, 1) not (0.707, 0.707)
            pairs.append({
                "value": {"text": complex_text(complex(values[i])), "real": float(np.real(values[i])),
                          "imag": float(np.imag(values[i]))},
                "vector": [complex_text(complex(c)) for c in vector],
            })
        poly = characteristic_polynomial(a)
        result.update(result_type="eigen", pairs=pairs, symmetric=symmetric, polynomial=polynomial_text(poly),
                      determinant=cell(determinant(a)), trace=cell(trace(a)))
        summary = f"Eigenvalues of a {size_text(a)} matrix: " + ", ".join(p["value"]["text"] for p in pairs)

    result["summary"] = summary
    result["saved"] = save_history("matrix", summary, inputs, {"operation": op})
    result["served_by"] = HOSTNAME
    return jsonify(result)


# ---------------------------------------------------------------------------
# /vector3d
# ---------------------------------------------------------------------------

def read_vector(data, field, label):
    raw = data.get(field)
    if not isinstance(raw, list) or len(raw) != 3:
        raise BadInput(f"Vector {label} needs three components: x, y and z", field)
    return np.array([float(to_fraction(v, f"{label} {axis}", field)) for v, axis in zip(raw, "xyz")])


def num(value, digits=10):
    if value is None or not math.isfinite(value):
        return None
    value = float(f"{value:.{digits}g}")
    return 0.0 if abs(value) < 1e-12 else value


def vec(values):
    return [num(v) for v in values]


def vec_text(values):
    return "(" + ", ".join(float_text(v) for v in vec(values)) + ")"


@app.post("/vector3d")
def vector3d():
    data = json_body()
    a = read_vector(data, "a", "a")
    b = read_vector(data, "b", "b")
    c = read_vector(data, "c", "c") if data.get("c") not in (None, "", []) else None

    mag_a, mag_b = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    dot = float(np.dot(a, b))
    cross = np.cross(a, b)
    cross_mag = float(np.linalg.norm(cross))
    scale = max(mag_a * mag_b, 1e-300)

    angle = None
    if mag_a > 0 and mag_b > 0:
        cosine = max(-1.0, min(1.0, dot / (mag_a * mag_b)))
        angle = math.acos(cosine)

    result = {
        "a": vec(a), "b": vec(b), "c": vec(c) if c is not None else None,
        "magnitude_a": num(mag_a), "magnitude_b": num(mag_b),
        "unit_a": vec(a / mag_a) if mag_a > 0 else None,
        "unit_b": vec(b / mag_b) if mag_b > 0 else None,
        "sum": vec(a + b), "difference": vec(a - b),
        "dot": num(dot), "cross": vec(cross), "cross_magnitude": num(cross_mag),
        "angle_degrees": num(math.degrees(angle)) if angle is not None else None,
        "angle_radians": num(angle) if angle is not None else None,
        "projection_scalar": num(dot / mag_b) if mag_b > 0 else None,
        "projection_vector": vec(dot / (mag_b ** 2) * b) if mag_b > 0 else None,
        "parallelogram_area": num(cross_mag),
        "triangle_area": num(cross_mag / 2),
        "perpendicular": bool(mag_a > 0 and mag_b > 0 and abs(dot) < 1e-9 * scale),
        "parallel": bool(mag_a > 0 and mag_b > 0 and cross_mag < 1e-9 * scale),
        "triple_product": None,
        "coplanar": None,
    }
    if c is not None:
        triple = float(np.dot(a, np.cross(b, c)))
        result["triple_product"] = num(triple)
        result["coplanar"] = bool(abs(triple) < 1e-9 * max(mag_a * mag_b * float(np.linalg.norm(c)), 1e-300))

    summary = f"a = {vec_text(a)}, b = {vec_text(b)}: a·b = {float_text(num(dot))}, a×b = {vec_text(cross)}"
    if angle is not None:
        summary += f", angle {float_text(num(math.degrees(angle), 6))}°"
    inputs = {"a": [float_text(v).replace("−", "-") for v in vec(a)],
              "b": [float_text(v).replace("−", "-") for v in vec(b)],
              "c": [float_text(v).replace("−", "-") for v in vec(c)] if c is not None else None}
    result["summary"] = summary
    result["saved"] = save_history("vector3d", summary, inputs, {"dot": result["dot"], "cross": result["cross"]})
    result["served_by"] = HOSTNAME
    return jsonify(result)


if __name__ == "__main__":  # local development only; containers run gunicorn
    app.run(host="0.0.0.0", port=5000)

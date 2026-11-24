"""math-service: advanced maths for the Calculator Suite.

    GET  /functions    functions and constants the expression box understands
    GET  /solids       3D shapes and their measurements (the UI builds its form from this)
    POST /evaluate     {"expression": "sin(30)^2 + log(100)", "angle": "deg"}
    POST /plot2d       {"functions": ["sin(x)", "x^2/4"], "x_min": -10, "x_max": 10}
    POST /plot3d       {"mode": "surface", "expression": "sin(x)*cos(y)", "x_min": -5, ...}
    POST /calculus     {"expression": "x^3 - 3x", "x0": 1, "a": -2, "b": 2}
    POST /statistics   {"x": "4, 8, 15, 16, 23, 42", "mode": "sample"}
    POST /solid        {"shape": "cylinder", "dims": {"r": 3, "h": 10}, "unit": "cm"}
    GET  /health  /ready  /metrics

Graph results are cached in Redis, so drawing the same graph again is instant.
If Redis or history-service is down, everything still works; it just isn't cached or saved.
"""
import hashlib
import json
import math
import os
import re
import signal
import socket
import threading
import time
import warnings

import numpy as np
import redis
import requests
import sympy as sp
from flask import Flask, Response, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from werkzeug.exceptions import HTTPException

import analysis
import expr
import solids
from analysis import clean, to_grid, to_list

# Results that aren't real numbers (overflow, 0/0, log of a negative) are handled on purpose:
# they become gaps in a graph or a clear message. NumPy's warnings about them would only fill the logs.
warnings.filterwarnings("ignore", category=RuntimeWarning)

SERVICE = "math-service"
VERSION = "3.2.0"
HOSTNAME = socket.gethostname()  # container ID under Docker, pod name under Kubernetes
HISTORY_URL = os.environ.get("HISTORY_URL", "http://history-service:5000").rstrip("/")
REDIS_URL = os.environ.get("REDIS_URL", "redis://cache:6379/0")
CACHE_TTL = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))

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


def read_whole(data, field, label, default, minimum, maximum):
    if data.get(field) in (None, ""):
        return default
    number = read_number(data, field, label, minimum=minimum, maximum=maximum)
    if number != int(number):
        raise BadInput(f"{label} must be a whole number", field)
    return int(number)


def read_choice(data, field, label, choices, default):
    value = str(data.get(field, default)).strip().lower()
    if value not in choices:
        raise BadInput(f"{label} must be one of: " + ", ".join(choices), field)
    return value


def read_range(data, low_field, high_field, label, default, limit=1e6):
    """A from-to range; fields left out of the request use the default range."""
    values = {low_field: default[0], high_field: default[1]}
    values.update({k: data[k] for k in (low_field, high_field) if data.get(k) not in (None, "")})
    low = read_number(values, low_field, f"{label} from", minimum=-limit, maximum=limit)
    high = read_number(values, high_field, f"{label} to", minimum=-limit, maximum=limit)
    if low >= high:
        raise BadInput(f"The {label} range must go from a smaller number to a larger one", high_field)
    return low, high


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
    if value is None:
        return "undefined"
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
        "summary": summary[:500],
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
# Prometheus metrics (scraped from /metrics by the monitoring profile)
# ---------------------------------------------------------------------------

REQUESTS = Counter("http_requests_total", "HTTP requests handled", ["service", "method", "endpoint", "status"])
LATENCY = Histogram("http_request_duration_seconds", "Time taken to handle a request", ["service", "endpoint"],
                    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))
CACHE_LOOKUPS = Counter("cache_requests_total", "Graph cache lookups", ["service", "result"])
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
# Redis cache for graph results
# ---------------------------------------------------------------------------

class GraphCache:
    """Cache-aside with Redis. If Redis is down, wait 15 s before trying again."""

    def __init__(self, url):
        self.url = url
        self.client = None
        self.retry_at = 0.0

    def _connection(self):
        if not self.url or time.monotonic() < self.retry_at:
            return None
        if self.client is None:
            self.client = redis.Redis.from_url(self.url, socket_connect_timeout=0.3, socket_timeout=0.5)
        return self.client

    def _failed(self, exc):
        app.logger.warning("Cache unavailable: %s", exc)
        self.client = None
        self.retry_at = time.monotonic() + 15

    def get(self, key):
        client = self._connection()
        if client is None:
            return None
        try:
            return client.get(key)
        except redis.RedisError as exc:
            self._failed(exc)
            return None

    def set(self, key, value):
        client = self._connection()
        if client is None:
            return False
        try:
            client.setex(key, CACHE_TTL, value)
            return True
        except redis.RedisError as exc:
            self._failed(exc)
            return False

    def status(self):
        if not self.url:
            return "disabled"
        client = self._connection()
        if client is None:
            return "unavailable"
        try:
            client.ping()
            return "connected"
        except redis.RedisError as exc:
            self._failed(exc)
            return "unavailable"


cache = GraphCache(REDIS_URL)


def cached(endpoint, params, compute):
    """Return (result, from_cache). params must identify the result completely."""
    # The version is part of the key, so a new release never serves results worked out by the old code
    key = f"math:{VERSION}:{endpoint}:" + hashlib.sha256(
        json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    hit = cache.get(key)
    if hit is not None:
        CACHE_LOOKUPS.labels(SERVICE, "hit").inc()
        return json.loads(hit), True
    result = compute()
    stored = cache.set(key, json.dumps(result, separators=(",", ":")))
    CACHE_LOOKUPS.labels(SERVICE, "miss" if stored else "unavailable").inc()
    return result, False


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

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


@app.get("/ready")
def ready():
    return jsonify(service=SERVICE, status="ok", version=VERSION, cache=cache.status(), served_by=HOSTNAME)


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

def compile_expression(text, variables, field, label=None):
    if not isinstance(text, str) or not text.strip():
        raise BadInput(f"Enter {label or 'an expression'}", field)
    try:
        return expr.parse(text, variables)
    except expr.ExpressionError as err:
        prefix = f"{label}: " if label else ""
        raise BadInput(prefix + str(err), field) from None


def function_of(node, name, degrees=False):
    """node -> f(array) for one variable."""
    def f(values):
        values = np.asarray(values, dtype=float)
        return np.broadcast_to(expr.evaluate(node, {name: values}, degrees), values.shape).astype(float)
    return f


UNDEFINED = ("The answer is undefined. Check for division by zero, the square root or log of a "
             "negative number, or tan(90°).")


@app.get("/functions")
def functions():
    return jsonify(expr.function_catalogue())


@app.post("/evaluate")
def evaluate():
    data = json_body()
    text = str(data.get("expression", ""))
    angle = read_choice(data, "angle", "Angle unit", ("deg", "rad"), "deg")
    node = compile_expression(text, {"ans"}, "expression")
    env = {}
    if expr.uses_variable(node, "ans"):
        if data.get("ans") in (None, ""):
            raise BadInput("There's no previous answer yet", "expression")
        env["ans"] = read_number(data, "ans", "Previous answer")
    value = float(expr.evaluate(node, env, angle == "deg"))
    if math.isinf(value):
        raise BadInput("The answer is infinite or too large to show", "expression")
    if not math.isfinite(value):
        raise BadInput(UNDEFINED, "expression")
    value = clean(value)
    shown = expr.to_text(node)
    uses_angles = expr.uses_angles(node)
    unit = (" (degrees)" if angle == "deg" else " (radians)") if uses_angles else ""
    summary = f"{shown} = {fmt(value, 10)}{unit}"
    saved = save_history("scientific", summary, {"expression": text, "angle": angle},
                         {"result": value})
    return jsonify(expression=text, interpreted=shown, result=value, angle=angle, uses_angles=uses_angles,
                   summary=summary, saved=saved, served_by=HOSTNAME)


# ---------------------------------------------------------------------------
# 2D graphs
# ---------------------------------------------------------------------------

MAX_FUNCTIONS = 4


@app.post("/plot2d")
def plot2d():
    data = json_body()
    raw = data.get("functions")
    if not isinstance(raw, list):
        raise BadInput("Send functions as a list, for example [\"sin(x)\"]", "functions")
    texts = [str(item).strip() for item in raw if str(item).strip()]
    if not texts:
        raise BadInput("Enter at least one function", "f0")
    if len(texts) > MAX_FUNCTIONS:
        raise BadInput(f"Plot at most {MAX_FUNCTIONS} functions at once", "functions")
    x_min, x_max = read_range(data, "x_min", "x_max", "x", (-10, 10))
    points = read_whole(data, "points", "Points", 600, 50, 2000)
    angle = read_choice(data, "angle", "Angle unit", ("deg", "rad"), "rad")
    nodes = [compile_expression(text, {"x"}, f"f{i}", f"Function {i + 1}") for i, text in enumerate(texts)]
    params = {"functions": texts, "x_min": x_min, "x_max": x_max, "points": points, "angle": angle}

    def compute():
        xs = np.linspace(x_min, x_max, points)
        series, ranges, any_clipped = [], [], False
        for text, node in zip(texts, nodes):
            f = function_of(node, "x", angle == "deg")
            raw = f(xs)
            ys, suggested = analysis.tidy_series(f, xs, raw)
            roots, more_roots = analysis.find_roots(f, x_min, x_max)
            extrema, more_extrema = analysis.find_extrema(f, xs, raw)
            intercept = float(f(np.array([0.0]))[0]) if x_min <= 0 <= x_max else None
            finite = np.isfinite(ys)
            if suggested:
                any_clipped = True
                ranges.append(suggested)
            elif finite.any():
                ranges.append([float(ys[finite].min()), float(ys[finite].max())])
            series.append({
                "expression": text,
                "interpreted": expr.to_text(node),
                "y": to_list(ys),
                "roots": [clean(r, 10) for r in roots],
                "more_roots": more_roots,
                "extrema": extrema,
                "more_extrema": more_extrema,
                "y_intercept": clean(intercept, 10) if intercept is not None else None,
                "defined": bool(finite.any()),
            })
        y_range = None
        if any_clipped and ranges:   # poles: suggest a y-range that ignores the huge values near them
            low, high = min(r[0] for r in ranges), max(r[1] for r in ranges)
            y_range = [low, high] if high > low else None
        return {"x": to_list(xs), "series": series, "y_range": y_range, "x_min": x_min, "x_max": x_max,
                "angle": angle}

    result, from_cache = cached("plot2d", params, compute)
    if not any(s["defined"] for s in result["series"]):
        raise BadInput("None of the functions has a real value in this x range", "f0")
    summary = f"Plotted {', '.join(texts)} for {fmt(x_min)} ≤ x ≤ {fmt(x_max)}"
    # A graph loaded back from the history panel is sent with "history": false, so it isn't saved twice
    result["saved"] = save_history("plot2d", summary, params, {"functions": len(texts)}) if data.get("history", True) is not False else None
    result["cached"] = from_cache
    result["summary"] = summary
    result["served_by"] = HOSTNAME
    return jsonify(result)


# ---------------------------------------------------------------------------
# 3D graphs: surfaces z = f(x, y), curves (x(t), y(t), z(t)) and
# parametric surfaces (x(u, v), y(u, v), z(u, v))
# ---------------------------------------------------------------------------

@app.post("/plot3d")
def plot3d():
    data = json_body()
    mode = read_choice(data, "mode", "Mode", ("surface", "curve", "parametric"), "surface")
    angle = read_choice(data, "angle", "Angle unit", ("deg", "rad"), "rad")
    degrees = angle == "deg"

    if mode == "surface":
        text = str(data.get("expression", "")).strip()
        node = compile_expression(text, {"x", "y"}, "expression", "z")
        x_min, x_max = read_range(data, "x_min", "x_max", "x", (-5, 5), 1e4)
        y_min, y_max = read_range(data, "y_min", "y_max", "y", (-5, 5), 1e4)
        size = read_whole(data, "resolution", "Resolution", 60, 10, 120)
        params = {"mode": mode, "expression": text, "x": [x_min, x_max], "y": [y_min, y_max],
                  "resolution": size, "angle": angle}

        def compute():
            xs = np.linspace(x_min, x_max, size)
            ys = np.linspace(y_min, y_max, size)
            grid_x, grid_y = np.meshgrid(xs, ys)
            z = np.broadcast_to(expr.evaluate(node, {"x": grid_x, "y": grid_y}, degrees), grid_x.shape)
            z = np.where(np.isfinite(z), z, np.nan)
            z, clipped = analysis.clip_surface(z)
            finite = np.isfinite(z)
            if not finite.any():
                raise BadInput("z has no real values anywhere in this x and y range", "expression")
            return {"mode": mode, "x": to_list(xs), "y": to_list(ys), "z": to_grid(z),
                    "z_min": clean(float(z[finite].min())) if finite.any() else None,
                    "z_max": clean(float(z[finite].max())) if finite.any() else None,
                    "clipped": clipped, "undefined_points": int((~finite).sum()),
                    "interpreted": expr.to_text(node)}

        summary = f"3D surface z = {text}"
    else:
        names = {"curve": ("t",), "parametric": ("u", "v")}[mode]
        nodes = {axis: compile_expression(str(data.get(f"expr_{axis}", "")).strip(), set(names), f"expr_{axis}", axis)
                 for axis in ("x", "y", "z")}
        texts = {axis: str(data.get(f"expr_{axis}", "")).strip() for axis in ("x", "y", "z")}
        if mode == "curve":
            t_min, t_max = read_range(data, "t_min", "t_max", "t", (0, 2 * math.pi), 1e4)
            points = read_whole(data, "points", "Points", 800, 50, 3000)
            params = {"mode": mode, "expressions": texts, "t": [t_min, t_max], "points": points, "angle": angle}

            def compute():
                t = np.linspace(t_min, t_max, points)
                coords = {axis: np.broadcast_to(expr.evaluate(node, {"t": t}, degrees), t.shape)
                          for axis, node in nodes.items()}
                if not all(np.isfinite(values).any() for values in coords.values()):
                    raise BadInput("The curve has no real points in this t range", "expr_x")
                return {"mode": mode, "t": to_list(t), **{axis: to_list(values) for axis, values in coords.items()}}
        else:
            u_min, u_max = read_range(data, "u_min", "u_max", "u", (0, 2 * math.pi), 1e4)
            v_min, v_max = read_range(data, "v_min", "v_max", "v", (0, 2 * math.pi), 1e4)
            size = read_whole(data, "resolution", "Resolution", 50, 10, 100)
            params = {"mode": mode, "expressions": texts, "u": [u_min, u_max], "v": [v_min, v_max],
                      "resolution": size, "angle": angle}

            def compute():
                grid_u, grid_v = np.meshgrid(np.linspace(u_min, u_max, size), np.linspace(v_min, v_max, size))
                coords = {axis: np.broadcast_to(expr.evaluate(node, {"u": grid_u, "v": grid_v}, degrees), grid_u.shape)
                          for axis, node in nodes.items()}
                if not all(np.isfinite(values).any() for values in coords.values()):
                    raise BadInput("The surface has no real points in this u and v range", "expr_x")
                return {"mode": mode, **{axis: to_grid(values) for axis, values in coords.items()}}

        label = "3D curve" if mode == "curve" else "3D parametric surface"
        summary = f"{label} ({texts['x']}, {texts['y']}, {texts['z']})"

    result, from_cache = cached("plot3d", params, compute)
    result["saved"] = save_history("graph3d", summary, params, {"mode": mode}) if data.get("history", True) is not False else None
    result["cached"] = from_cache
    result["summary"] = summary
    result["served_by"] = HOSTNAME
    return jsonify(result)


# ---------------------------------------------------------------------------
# Calculus: derivative (exact, with SymPy), tangent, integral, roots, turning points
# ---------------------------------------------------------------------------

X = sp.Symbol("x", real=True)


def symbolic_derivatives(node):
    """(f'(x), f''(x)) as SymPy expressions, or (None, None) if that isn't possible."""
    try:
        f = expr.to_sympy(node, {"x": X})
        first = sp.diff(f, X)
        if first.has(sp.Derivative, sp.Subs):
            return None, None
        second = sp.diff(first, X)
        return first, (None if second.has(sp.Derivative, sp.Subs) else second)
    except expr.SymbolicUnsupported:
        return None, None
    except Exception:   # SymPy is a best-effort extra: fall back to numbers
        app.logger.warning("Symbolic derivative failed", exc_info=True)
        return None, None


def symbolic_value(expression, x0):
    try:
        value = complex(expression.subs(X, x0).evalf())
    except Exception:
        return None
    if abs(value.imag) > 1e-12 or not math.isfinite(value.real):
        return None
    return value.real


def line_text(slope, intercept):
    m, c = clean(slope, 6), clean(intercept, 6)
    if m == 0:
        return f"y = {fmt(c)}"
    slope_text = "" if m == 1 else "−" if m == -1 else fmt(m)
    text = f"y = {slope_text}x"
    if c:
        text += f" {'+' if c > 0 else '−'} {fmt(abs(c))}"
    return text.replace("y = -", "y = −")


@app.post("/calculus")
def calculus():
    data = json_body()
    text = str(data.get("expression", "")).strip()
    node = compile_expression(text, {"x"}, "expression", "f(x)")
    x0 = read_number(data, "x0", "Point x₀", minimum=-1e6, maximum=1e6)
    a = read_number(data, "a", "Lower limit a", minimum=-1e6, maximum=1e6)
    b = read_number(data, "b", "Upper limit b", minimum=-1e6, maximum=1e6)
    if a == b:
        raise BadInput("The limits a and b must be different", "b")
    f = function_of(node, "x")

    f_x0 = float(f(np.array([x0]))[0])
    if not math.isfinite(f_x0):
        raise BadInput(f"f(x) isn't defined at x = {fmt(x0)}. Choose another point.", "x0")

    first, second = symbolic_derivatives(node)
    slope = symbolic_value(first, x0) if first is not None else None
    exact = slope is not None
    if slope is None:
        slope = float(analysis.numeric_derivative(f, np.array([x0]))[0])
    if not math.isfinite(slope):
        raise BadInput(f"f(x) has no derivative at x = {fmt(x0)} (the graph is broken or vertical there)", "x0")
    intercept = f_x0 - slope * x0

    low, high = min(a, b), max(a, b)
    roots, more_roots = analysis.find_roots(f, low, high)
    integral = analysis.integrate(f, a, b, breaks=() if more_roots else roots)
    xs_range = np.linspace(low, high, 2001)
    extrema, more_extrema = analysis.find_extrema(f, xs_range, f(xs_range))

    # Graph data: f, f', the tangent at x0 and the area between a and b
    left, right = min(low, x0), max(high, x0)
    pad = 0.15 * (right - left) or 1.0
    xs = np.linspace(left - pad, right + pad, 600)
    ys, y_range = analysis.tidy_series(f, xs, f(xs))
    dys, _ = analysis.tidy_series(lambda v: analysis.numeric_derivative(f, v), xs, analysis.numeric_derivative(f, xs))
    half = 0.25 * (xs[-1] - xs[0])
    tangent_x = np.array([x0 - half, x0 + half])
    area_x = np.linspace(low, high, 300)

    result = {
        "expression": text,
        "interpreted": expr.to_text(node),
        "x0": x0,
        "f_x0": clean(f_x0, 10),
        "derivative": {
            "text": expr.sympy_text(first)[:400] if first is not None else None,
            "second_text": expr.sympy_text(second)[:400] if second is not None else None,
            "value": clean(slope, 10),
            "exact": exact,
        },
        "tangent": {"slope": clean(slope, 10), "intercept": clean(intercept, 10), "text": line_text(slope, intercept)},
        "integral": ({"a": a, "b": b, "value": clean(integral[0], 10), "area": clean(integral[1], 10), "defined": True}
                     if integral is not None else
                     {"a": a, "b": b, "value": None, "area": None, "defined": False,
                      "message": "f(x) isn't defined at every point between a and b, so the integral can't be worked out"}),
        "roots": [clean(r, 10) for r in roots],
        "more_roots": more_roots,
        "extrema": extrema,
        "more_extrema": more_extrema,
        "plot": {
            "x": to_list(xs), "f": to_list(ys), "df": to_list(dys), "y_range": y_range,
            "tangent": {"x": to_list(tangent_x, 10), "y": to_list(slope * tangent_x + intercept, 10)},
            "area": {"x": to_list(area_x), "y": to_list(f(area_x))},
        },
    }
    parts = [f"f(x) = {text}"]
    if first is not None:
        parts.append(f"f'(x) = {result['derivative']['text']}")
    if integral is not None:
        parts.append(f"∫ from {fmt(a)} to {fmt(b)} = {fmt(integral[0])}")
    summary = ", ".join(parts)
    result["summary"] = summary
    result["saved"] = save_history("calculus", summary, {"expression": text, "x0": x0, "a": a, "b": b},
                                   {"derivative_at_x0": result["derivative"]["value"],
                                    "integral": result["integral"]["value"]})
    result["served_by"] = HOSTNAME
    return jsonify(result)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

MAX_VALUES = 5000


def read_values(data, field, label):
    raw = data.get(field)
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        items = [item for item in re.split(r"[\s,;]+", raw.strip()) if item]
    else:
        items = []
    if not items:
        raise BadInput(f"Enter some {label.lower()}", field)
    if len(items) > MAX_VALUES:
        raise BadInput(f"Enter at most {MAX_VALUES:,} values", field)
    values = []
    for item in items:
        try:
            number = float(item) if not isinstance(item, bool) else math.nan
        except (TypeError, ValueError):
            raise BadInput(f"'{str(item)[:20]}' isn't a number. Separate values with commas or spaces.", field) from None
        if not math.isfinite(number):
            raise BadInput(f"'{str(item)[:20]}' isn't a usable number", field)
        values.append(number)
    return values


@app.post("/statistics")
def statistics():
    data = json_body()
    xs = read_values(data, "x", "Values")
    mode = read_choice(data, "mode", "Mode", ("sample", "population"), "sample")
    ys = None
    if data.get("y") not in (None, "", []):
        ys = read_values(data, "y", "Y values")
        if len(ys) != len(xs):
            raise BadInput(f"Enter the same number of y values as x values ({len(xs)} x, {len(ys)} y)", "y")
        if len(xs) < 2:
            raise BadInput("A line of best fit needs at least 2 pairs of values", "y")
        if max(xs) == min(xs):
            raise BadInput("For a line of best fit, the x values can't all be the same", "x")

    result = analysis.describe(xs, sample=(mode == "sample"))
    result["mode"] = mode
    result["x"] = [clean(v) for v in xs]
    result["regression"] = None
    if ys is not None:
        result["y"] = [clean(v) for v in ys]
        result["regression"] = analysis.regression(xs, ys)

    summary = (f"{len(xs)} value{'s' if len(xs) != 1 else ''}: mean {fmt(result['mean'])}, "
               f"median {fmt(result['median'])}, SD {fmt(result['std'])}")
    if result["regression"]:
        reg = result["regression"]
        result["regression"]["equation"] = line_text(reg["slope"], reg["intercept"])
        summary += f"; best fit {result['regression']['equation']}"
    result["summary"] = summary
    result["saved"] = save_history("statistics", summary,
                                   {"x": " ".join(f"{v:.10g}" for v in xs[:500]),
                                    "y": " ".join(f"{v:.10g}" for v in ys[:500]) if ys else "",
                                    "mode": mode},
                                   {"mean": result["mean"], "std": result["std"]})
    result["served_by"] = HOSTNAME
    return jsonify(result)


# ---------------------------------------------------------------------------
# 3D shapes
# ---------------------------------------------------------------------------

UNITS = ("mm", "cm", "m", "in", "ft")


@app.get("/solids")
def solid_catalogue():
    return jsonify(shapes=solids.catalogue(), units=list(UNITS))


@app.post("/solid")
def solid():
    data = json_body()
    shape = read_choice(data, "shape", "Shape", tuple(solids.SHAPES), "cube")
    unit = read_choice(data, "unit", "Unit", UNITS, "cm")
    raw_dims = data.get("dims") if isinstance(data.get("dims"), dict) else {}
    name, dim_specs = solids.SHAPES[shape]
    dims = {}
    for key, label in dim_specs:
        may_be_zero = shape == "frustum" and key == "r"   # a frustum with r = 0 is a cone
        dims[key] = read_number(raw_dims, key, label, minimum=0 if may_be_zero else None, maximum=1e6,
                                positive=not may_be_zero)
    try:
        measurements = solids.measure(shape, dims)
    except ValueError as err:
        raise BadInput(str(err), dim_specs[-1][0]) from None

    unit_suffix = {"volume": f"{unit}³", "area": f"{unit}²", "length": unit}
    results = [{"label": label, "value": clean(value, 10), "unit": unit_suffix[kind], "kind": kind, "formula": formula}
               for label, value, kind, formula in measurements]
    volume = next(r["value"] for r in results if r["kind"] == "volume")
    litres = clean(volume * solids.LITRES_PER_CUBIC_UNIT[unit], 10)
    dims_text = ", ".join(f"{key} = {fmt(value)} {unit}" for key, value in dims.items())
    summary = f"{name} ({dims_text}): volume {fmt(volume)} {unit}³"
    saved = save_history("solid", summary, {"shape": shape, "dims": dims, "unit": unit},
                         {"volume": volume, "litres": litres})
    return jsonify(shape=shape, name=name, unit=unit, dims=dims, results=results, litres=litres,
                   summary=summary, saved=saved, served_by=HOSTNAME)


if __name__ == "__main__":  # local development only; containers run gunicorn
    app.run(host="0.0.0.0", port=5000)

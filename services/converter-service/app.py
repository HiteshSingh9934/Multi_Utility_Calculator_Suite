"""converter-service: converts between units in 10 categories.

    GET  /units      every category and its units (the UI builds its menus from this)
    POST /convert    {"category": "length", "value": 10, "from_unit": "km", "to_unit": "mi"}
    GET  /health
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

SERVICE = "converter-service"
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
    """Best effort: if history-service is down, the conversion still succeeds."""
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
# Unit tables. Each unit is (id, name, symbol, factor), where factor is how
# many of the category's base unit one of this unit equals.
# ---------------------------------------------------------------------------

CATEGORIES = {
    "length": {
        "name": "Length",
        "base": "metre",
        "default": ("km", "mi"),
        "units": [
            ("nm", "Nanometre", "nm", 1e-9),
            ("um", "Micrometre", "µm", 1e-6),
            ("mm", "Millimetre", "mm", 0.001),
            ("cm", "Centimetre", "cm", 0.01),
            ("m", "Metre", "m", 1.0),
            ("km", "Kilometre", "km", 1000.0),
            ("in", "Inch", "in", 0.0254),
            ("ft", "Foot", "ft", 0.3048),
            ("yd", "Yard", "yd", 0.9144),
            ("mi", "Mile", "mi", 1609.344),
            ("nmi", "Nautical mile", "nmi", 1852.0),
        ],
    },
    "weight": {
        "name": "Weight",
        "base": "kilogram",
        "default": ("kg", "lb"),
        "units": [
            ("mg", "Milligram", "mg", 1e-6),
            ("g", "Gram", "g", 0.001),
            ("kg", "Kilogram", "kg", 1.0),
            ("q", "Quintal", "q", 100.0),
            ("t", "Tonne", "t", 1000.0),
            ("ct", "Carat", "ct", 0.0002),
            ("oz", "Ounce", "oz", 0.028349523125),
            ("lb", "Pound", "lb", 0.45359237),
            ("st", "Stone", "st", 6.35029318),
        ],
    },
    "temperature": {
        "name": "Temperature",
        "base": "degree Celsius",
        "default": ("c", "f"),
        "units": [
            ("c", "Celsius", "°C", None),
            ("f", "Fahrenheit", "°F", None),
            ("k", "Kelvin", "K", None),
        ],
    },
    "area": {
        "name": "Area",
        "base": "square metre",
        "default": ("m2", "ft2"),
        "units": [
            ("mm2", "Square millimetre", "mm²", 1e-6),
            ("cm2", "Square centimetre", "cm²", 1e-4),
            ("in2", "Square inch", "in²", 0.00064516),
            ("ft2", "Square foot", "ft²", 0.09290304),
            ("yd2", "Square yard", "yd²", 0.83612736),
            ("m2", "Square metre", "m²", 1.0),
            ("guntha", "Guntha", "guntha", 101.17141056),  # 1,089 sq ft
            ("ac", "Acre", "ac", 4046.8564224),
            ("ha", "Hectare", "ha", 10000.0),
            ("km2", "Square kilometre", "km²", 1e6),
            ("mi2", "Square mile", "mi²", 2589988.110336),
        ],
    },
    "volume": {
        "name": "Volume",
        "base": "litre",
        "default": ("l", "gal"),
        "units": [
            ("ml", "Millilitre", "mL", 0.001),
            ("cm3", "Cubic centimetre", "cm³", 0.001),
            ("l", "Litre", "L", 1.0),
            ("m3", "Cubic metre", "m³", 1000.0),
            ("tsp", "Teaspoon (US)", "tsp", 0.00492892159375),
            ("tbsp", "Tablespoon (US)", "tbsp", 0.01478676478125),
            ("floz", "Fluid ounce (US)", "fl oz", 0.0295735295625),
            ("cup", "Cup (US)", "cup", 0.2365882365),
            ("pt", "Pint (US)", "pt", 0.473176473),
            ("qt", "Quart (US)", "qt", 0.946352946),
            ("gal", "Gallon (US)", "gal", 3.785411784),
            ("galuk", "Gallon (UK)", "gal (UK)", 4.54609),
            ("in3", "Cubic inch", "in³", 0.016387064),
            ("ft3", "Cubic foot", "ft³", 28.316846592),
        ],
    },
    "speed": {
        "name": "Speed",
        "base": "metre per second",
        "default": ("kmph", "mph"),
        "units": [
            ("kmph", "Kilometre per hour", "km/h", 1 / 3.6),
            ("mps", "Metre per second", "m/s", 1.0),
            ("mph", "Mile per hour", "mph", 0.44704),
            ("fps", "Foot per second", "ft/s", 0.3048),
            ("kn", "Knot", "kn", 1852 / 3600),
        ],
    },
    "time": {
        "name": "Time",
        "base": "second",
        "default": ("h", "min"),
        "units": [
            ("ms", "Millisecond", "ms", 0.001),
            ("s", "Second", "s", 1.0),
            ("min", "Minute", "min", 60.0),
            ("h", "Hour", "h", 3600.0),
            ("d", "Day", "d", 86400.0),
            ("wk", "Week", "wk", 604800.0),
            ("yr", "Year (365 days)", "yr", 31536000.0),
        ],
    },
    "data": {
        "name": "Data",
        "base": "byte",
        "default": ("gb", "mb"),
        "units": [
            ("bit", "Bit", "bit", 0.125),
            ("b", "Byte", "B", 1.0),
            ("kb", "Kilobyte", "KB", 1e3),
            ("kib", "Kibibyte", "KiB", 1024.0),
            ("mb", "Megabyte", "MB", 1e6),
            ("mib", "Mebibyte", "MiB", 1024.0 ** 2),
            ("gb", "Gigabyte", "GB", 1e9),
            ("gib", "Gibibyte", "GiB", 1024.0 ** 3),
            ("tb", "Terabyte", "TB", 1e12),
            ("tib", "Tebibyte", "TiB", 1024.0 ** 4),
        ],
    },
    "energy": {
        "name": "Energy",
        "base": "joule",
        "default": ("kcal", "kj"),
        "units": [
            ("j", "Joule", "J", 1.0),
            ("kj", "Kilojoule", "kJ", 1000.0),
            ("cal", "Calorie", "cal", 4.184),
            ("kcal", "Kilocalorie", "kcal", 4184.0),
            ("wh", "Watt-hour", "Wh", 3600.0),
            ("kwh", "Kilowatt-hour", "kWh", 3.6e6),
            ("btu", "British thermal unit", "BTU", 1055.05585262),
            ("ev", "Electronvolt", "eV", 1.602176634e-19),
        ],
    },
    "pressure": {
        "name": "Pressure",
        "base": "pascal",
        "default": ("bar", "psi"),
        "units": [
            ("pa", "Pascal", "Pa", 1.0),
            ("kpa", "Kilopascal", "kPa", 1000.0),
            ("bar", "Bar", "bar", 1e5),
            ("atm", "Atmosphere", "atm", 101325.0),
            ("psi", "Pound per square inch", "psi", 6894.757293168),
            ("mmhg", "Millimetre of mercury", "mmHg", 133.322387415),
        ],
    },
}

ABSOLUTE_ZERO_C = -273.15


def unit_lookup(category_id, unit_id, field):
    for unit in CATEGORIES[category_id]["units"]:
        if unit[0] == unit_id:
            return unit
    names = ", ".join(u[0] for u in CATEGORIES[category_id]["units"])
    raise BadInput(f"Unknown unit '{unit_id}'. Choose one of: {names}", field)


def to_celsius(value, unit_id):
    if unit_id == "c":
        return value
    if unit_id == "f":
        return (value - 32) * 5 / 9
    return value + ABSOLUTE_ZERO_C  # kelvin


def from_celsius(value, unit_id):
    if unit_id == "c":
        return value
    if unit_id == "f":
        return value * 9 / 5 + 32
    return value - ABSOLUTE_ZERO_C  # kelvin


def convert_value(category_id, value, from_id, to_id):
    if category_id == "temperature":
        celsius = to_celsius(value, from_id)
        if celsius < ABSOLUTE_ZERO_C - 1e-9:
            raise BadInput("That is colder than absolute zero (−273.15 °C)", "value")
        return clean(from_celsius(celsius, to_id))
    from_factor = unit_lookup(category_id, from_id, "from_unit")[3]
    to_factor = unit_lookup(category_id, to_id, "to_unit")[3]
    return clean(value * from_factor / to_factor)


@app.get("/units")
def units():
    categories = []
    for category_id, category in CATEGORIES.items():
        categories.append({
            "id": category_id,
            "name": category["name"],
            "base": category["base"],
            "default_from": category["default"][0],
            "default_to": category["default"][1],
            "units": [{"id": u[0], "name": u[1], "symbol": u[2]} for u in category["units"]],
        })
    return jsonify(categories=categories)


@app.post("/convert")
def convert():
    data = json_body()
    category_id = str(data.get("category", "")).strip().lower()
    if category_id not in CATEGORIES:
        raise BadInput("Choose one of: " + ", ".join(CATEGORIES), "category")
    value = read_number(data, "value", "Value")
    from_unit = unit_lookup(category_id, str(data.get("from_unit", "")).strip().lower(), "from_unit")
    to_unit = unit_lookup(category_id, str(data.get("to_unit", "")).strip().lower(), "to_unit")

    result = convert_value(category_id, value, from_unit[0], to_unit[0])
    summary = f"{fmt(value)} {from_unit[2]} = {fmt(result)} {to_unit[2]}"

    response = {
        "category": category_id,
        "category_name": CATEGORIES[category_id]["name"],
        "value": value,
        "from_unit": from_unit[0],
        "from_symbol": from_unit[2],
        "to_unit": to_unit[0],
        "to_symbol": to_unit[2],
        "result": result,
        "summary": summary,
    }
    if data.get("include_all"):
        response["all"] = [
            {
                "unit": unit[0],
                "name": unit[1],
                "symbol": unit[2],
                "value": convert_value(category_id, value, from_unit[0], unit[0]),
            }
            for unit in CATEGORIES[category_id]["units"]
        ]

    response["saved"] = save_history(
        "unit-converter",
        summary,
        {"category": category_id, "value": value, "from_unit": from_unit[0], "to_unit": to_unit[0]},
        {"result": result},
    )
    response["served_by"] = HOSTNAME
    return jsonify(response)


if __name__ == "__main__":  # local development only; containers run gunicorn
    app.run(host="0.0.0.0", port=5000)

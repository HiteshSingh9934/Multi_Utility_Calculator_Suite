"""history-service: the only microservice that talks to PostgreSQL.

    POST   /records           save one result (called by the other services on the internal network)
    GET    /records?limit=20  newest results first (optionally &tool=gst)
    DELETE /records           clear all history
    GET    /stats             how many results are saved, per tool
    GET    /health            is the process alive?          (Docker/Kubernetes liveness)
    GET    /ready             can it reach the database?     (Docker/Kubernetes readiness)
"""
import os
import signal
import socket
import threading
import time
from pathlib import Path

import psycopg2
import psycopg2.errors
from psycopg2 import extras, pool
from flask import Flask, Response, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from werkzeug.exceptions import HTTPException

SERVICE = "history-service"
VERSION = "3.2.0"
HOSTNAME = socket.gethostname()  # container ID under Docker, pod name under Kubernetes

def read_password():
    """Docker secrets arrive as a file (DB_PASSWORD_FILE); plain DB_PASSWORD still works."""
    path = os.environ.get("DB_PASSWORD_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SystemExit(f"Can't read the database password from {path}: {exc}") from exc
    return os.environ.get("DB_PASSWORD", "calc_password")


DB_SETTINGS = {
    "host": os.environ.get("DB_HOST", "db"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "dbname": os.environ.get("DB_NAME", "calculator"),
    "user": os.environ.get("DB_USER", "calc_user"),
    "password": read_password(),
    "connect_timeout": 3,
    "application_name": SERVICE,
}

SCHEMA_SQL = Path(__file__).with_name("schema.sql").read_text()
SCHEMA_LOCK = 724_001  # advisory lock id: only one replica creates/migrates the schema at a time

# Version 1 of the project stored basic calculations in a "calculations" table.
# Copy them into the new history table once, so an upgrade keeps old history.
IMPORT_V1_SQL = """
INSERT INTO history (tool, service, summary, input, result, served_by, created_at)
SELECT 'calculator',
       'calc-service',
       format('%s %s %s = %s', c.num1,
              CASE c.operation WHEN 'add' THEN '+' WHEN 'subtract' THEN '−'
                               WHEN 'multiply' THEN '×' WHEN 'divide' THEN '÷'
                               ELSE c.operation END,
              c.num2, c.result),
       jsonb_build_object('num1', c.num1, 'num2', c.num2, 'operation', c.operation, 'v1_id', c.id),
       jsonb_build_object('result', c.result),
       NULL,
       c.created_at
FROM calculations c
"""

TOOLS = {"calculator", "unit-converter", "gst", "emi", "cgpa", "grades", "attendance",
         "scientific", "plot2d", "graph3d", "calculus", "statistics", "solid", "matrix", "vector3d", "solver"}

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
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


@app.errorhandler(psycopg2.OperationalError)
@app.errorhandler(psycopg2.InterfaceError)
def handle_database_down(err):
    app.logger.warning("Database unavailable: %s", err)
    return jsonify(error="The database is unavailable right now"), 503


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
        raise BadInput("Send the record as a JSON object")
    return data


# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------

_pool = None
_pool_lock = threading.Lock()
_schema_ready = False


def get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = pool.ThreadedConnectionPool(1, 8, **DB_SETTINGS)
        return _pool


def drop_pool(stale):
    """Throw away every pooled connection, e.g. after the database restarted."""
    global _pool
    with _pool_lock:
        if _pool is stale:
            try:
                _pool.closeall()
            except pool.PoolError:
                pass
            _pool = None


def run(work):
    """Run work(cursor) in one transaction, retrying once on a dead connection."""
    for attempt in (1, 2):
        db = get_pool()
        conn = db.getconn()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                result = work(cur)
            conn.commit()
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            drop_pool(db)
            if attempt == 2:
                raise
            time.sleep(0.2)
            continue
        except Exception:
            if not conn.closed:
                conn.rollback()
            db.putconn(conn)
            raise
        db.putconn(conn)
        return result


def ensure_schema():
    """Create the tables if needed and import version-1 history once."""
    global _schema_ready
    if _schema_ready:
        return

    def work(cur):
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK,))
        cur.execute(SCHEMA_SQL)
        cur.execute(
            "SELECT to_regclass('public.calculations') IS NOT NULL AS has_v1, "
            "EXISTS (SELECT 1 FROM migrations WHERE name = 'import-v1-calculations') AS done"
        )
        row = cur.fetchone()
        if row["has_v1"] and not row["done"]:
            cur.execute(IMPORT_V1_SQL)
            imported = cur.rowcount
            cur.execute("INSERT INTO migrations (name) VALUES ('import-v1-calculations')")
            return imported
        return 0

    imported = run(work)
    if imported:
        app.logger.warning("Imported %s calculations from version 1", imported)
    _schema_ready = True


def query(work):
    global _schema_ready
    ensure_schema()
    try:
        return run(work)
    except psycopg2.errors.UndefinedTable:
        _schema_ready = False  # the database was recreated while we were running
        ensure_schema()
        return run(work)


def serialise(row):
    row = dict(row)
    row["created_at"] = row["created_at"].isoformat()
    return row


# ---------------------------------------------------------------------------
# Routes
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
    try:
        query(lambda cur: cur.execute("SELECT 1"))
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
        reason = (str(exc).strip().splitlines() or ["no response"])[0]
        return jsonify(service=SERVICE, status="unavailable", database="unreachable",
                       error=reason, served_by=HOSTNAME), 503
    return jsonify(service=SERVICE, status="ok", database="connected", version=VERSION,
                   served_by=HOSTNAME)


@app.post("/records")
def add_record():
    data = json_body()
    tool = str(data.get("tool", "")).strip()
    if tool not in TOOLS:
        raise BadInput("Unknown tool", "tool")
    summary = str(data.get("summary", "")).strip()[:500]
    if not summary:
        raise BadInput("Summary is required", "summary")
    service = str(data.get("service") or "unknown").strip()[:40]
    served_by = (str(data.get("served_by") or "").strip()[:100]) or None
    inputs = data.get("input") if isinstance(data.get("input"), dict) else {}
    result = data.get("result") if isinstance(data.get("result"), dict) else {}

    def work(cur):
        cur.execute(
            "INSERT INTO history (tool, service, summary, input, result, served_by) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, created_at",
            (tool, service, summary, extras.Json(inputs), extras.Json(result), served_by),
        )
        return cur.fetchone()

    row = query(work)
    return jsonify(id=row["id"], created_at=row["created_at"].isoformat()), 201


@app.get("/records")
def list_records():
    limit = request.args.get("limit", default=20, type=int)
    limit = max(1, min(limit or 20, 100))
    tool = request.args.get("tool", "").strip()

    def work(cur):
        sql = ("SELECT id, tool, service, summary, input, result, served_by, created_at "
               "FROM history ")
        params = []
        if tool:
            sql += "WHERE tool = %s "
            params.append(tool)
        sql += "ORDER BY created_at DESC, id DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        return cur.fetchall()

    rows = [serialise(r) for r in query(work)]
    return jsonify(records=rows, count=len(rows), served_by=HOSTNAME)


@app.delete("/records")
def clear_records():
    def work(cur):
        cur.execute("DELETE FROM history")
        return cur.rowcount

    deleted = query(work)
    return jsonify(deleted=deleted, served_by=HOSTNAME)


@app.get("/stats")
def stats():
    def work(cur):
        cur.execute("SELECT tool, COUNT(*) AS count FROM history GROUP BY tool ORDER BY count DESC, tool")
        by_tool = {r["tool"]: r["count"] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) AS total, MIN(created_at) AS first_at, MAX(created_at) AS last_at "
                    "FROM history")
        totals = cur.fetchone()
        return by_tool, totals

    by_tool, totals = query(work)
    return jsonify(
        total=totals["total"],
        by_tool=by_tool,
        first_at=totals["first_at"].isoformat() if totals["first_at"] else None,
        last_at=totals["last_at"].isoformat() if totals["last_at"] else None,
        served_by=HOSTNAME,
    )


if __name__ == "__main__":  # local development only; containers run gunicorn
    app.run(host="0.0.0.0", port=5000)

"""Load a microservice's Flask app for testing, straight from services/<name>/app.py.

Every service has its own app.py, so they are loaded by file path under different module
names. Nothing else needs to be running: history-service and Redis are pointed at an address
where nothing listens, which also checks that a result still comes back when saving fails.
"""
import importlib.util
import os
import sys
from pathlib import Path

from prometheus_client import REGISTRY, CollectorRegistry, generate_latest

SERVICES = Path(__file__).resolve().parents[2] / "services"

os.environ["HISTORY_URL"] = "http://127.0.0.1:9"        # nothing listens on port 9
os.environ["REDIS_URL"] = "redis://127.0.0.1:9/0"        # so the graph cache is skipped too
os.environ["DB_HOST"] = "127.0.0.1"                      # and the database is "down"
os.environ["DB_PORT"] = "9"


def load_service(name):
    """services/<name>/app.py -> the imported module (its Flask app is module.app)."""
    folder = SERVICES / name
    existing = set(REGISTRY._collector_to_names)
    sys.path.insert(0, str(folder))       # math-service imports its own expr.py, analysis.py and solids.py
    try:
        spec = importlib.util.spec_from_file_location(name.replace("-", "_"), folder / "app.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(folder))

    # In Docker each service is its own process with its own metrics. Here they share one process,
    # so move the metrics this service just created into a registry of its own; otherwise the next
    # service's http_requests_total would clash with this one's.
    own = CollectorRegistry()
    for collector in set(REGISTRY._collector_to_names) - existing:
        REGISTRY.unregister(collector)
        own.register(collector)
    module.generate_latest = lambda registry=own: generate_latest(registry)

    module.app.testing = True
    return module


def post(client, path, body, status=200):
    """POST JSON and check the status code; returns the JSON reply."""
    response = client.post(path, json=body)
    assert response.status_code == status, (response.status_code, response.get_json())
    return response.get_json()

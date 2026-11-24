"""The chaos lab: every microservice can be broken on purpose, only when CHAOS_ENABLED is on."""
import os
import re
import signal
import time

import pytest

from service_loader import load_service

NAMES = ["calc-service", "converter-service", "finance-service", "student-service",
         "math-service", "matrix-service", "history-service"]
MODULES = {name: load_service(name) for name in NAMES}


@pytest.fixture(params=NAMES)
def lab(request, monkeypatch):
    """(module, client) with the chaos lab switched on and no fault active."""
    module = MODULES[request.param]
    monkeypatch.setattr(module, "CHAOS_ENABLED", True)
    monkeypatch.setattr(module, "CHAOS_SLOW_SECONDS", 0.05)
    module._chaos.update(mode=None, until=0.0)
    yield module, module.app.test_client()
    module._chaos.update(mode=None, until=0.0)


@pytest.mark.parametrize("name", NAMES)
def test_switched_off_by_default(name):
    client = MODULES[name].app.test_client()
    for response in (client.get("/chaos"), client.post("/chaos", json={"mode": "errors"})):
        assert response.status_code == 404
        assert response.get_json()["code"] == "chaos_disabled"
    # ... and nothing was injected
    assert client.get("/nothing-here").status_code == 404


def test_errors_mode_fails_requests_but_not_the_health_check(lab):
    module, client = lab
    reply = client.post("/chaos", json={"mode": "errors", "seconds": 30})
    assert reply.status_code == 200 and reply.get_json()["mode"] == "errors"

    failed = client.get("/anything")
    assert failed.status_code == 500
    assert failed.get_json()["code"] == "chaos"

    health = client.get("/health")                      # the checks keep telling the truth
    assert health.status_code == 200
    body = health.get_json()
    assert body["chaos"]["mode"] == "errors" and 0 < body["chaos"]["seconds_left"] <= 30
    assert client.get("/metrics").status_code == 200

    assert client.post("/chaos", json={"mode": "heal"}).get_json()["mode"] == "heal"
    assert client.get("/anything").status_code == 404   # a normal "no such page" again
    assert client.get("/health").get_json()["chaos"] is None


def test_slow_mode_delays_requests(lab):
    module, client = lab
    client.post("/chaos", json={"mode": "slow", "seconds": 30})
    started = time.perf_counter()
    assert client.get("/anything").status_code == 404
    assert time.perf_counter() - started >= 0.05
    started = time.perf_counter()
    client.get("/health")                                # never slowed
    assert time.perf_counter() - started < 0.05


def test_a_fault_ends_by_itself(lab):
    module, client = lab
    client.post("/chaos", json={"mode": "errors", "seconds": 5})
    module._chaos["until"] = time.time() - 1             # pretend the time is up
    assert client.get("/anything").status_code == 404
    assert client.get("/chaos").get_json()["chaos"] is None


def test_crash_stops_the_process_after_answering(lab, monkeypatch):
    module, client = lab
    calls = []
    monkeypatch.setattr(module, "stop_this_process", lambda server: calls.append(server))
    monkeypatch.setattr(module.threading, "Timer", lambda delay, fn, args: type(
        "FakeTimer", (), {"start": lambda self: fn(*args)})())
    reply = client.post("/chaos", json={"mode": "crash"})
    assert reply.status_code == 202
    assert calls == [""]                                 # the test client is not a real server


def test_stop_this_process_picks_the_right_way(lab, monkeypatch):
    module, _ = lab
    killed, exited = [], []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(os, "_exit", lambda code: exited.append(code))
    module.stop_this_process("gunicorn/26.2.0")          # the container's server: stop gunicorn's master
    assert killed == [(os.getppid(), signal.SIGTERM)] and exited == []
    module.stop_this_process("Werkzeug/3.1")             # flask run
    assert exited == [1]
    module.stop_this_process("")                         # tests: nothing happens
    assert len(killed) == 1 and exited == [1]


def test_bad_requests_are_explained(lab):
    _, client = lab
    assert client.post("/chaos", json={"mode": "explode"}).status_code == 400
    assert client.post("/chaos", json={"mode": "slow", "seconds": 2}).status_code == 400
    assert client.post("/chaos", json={"mode": "slow", "seconds": "soon"}).status_code == 400
    assert client.post("/chaos", data="nope", content_type="text/plain").status_code == 400


def test_chaos_is_counted_for_prometheus(lab):
    module, client = lab
    client.post("/chaos", json={"mode": "errors", "seconds": 5})
    client.post("/chaos", json={"mode": "heal"})
    text = client.get("/metrics").get_data(as_text=True)
    match = re.search(rf'chaos_injections_total\{{mode="errors",service="{module.SERVICE}"\}} (\d+)', text)
    assert match and int(match.group(1)) >= 1          # the counter only ever grows


@pytest.mark.parametrize("name", NAMES)
def test_health_reports_uptime(name):
    body = MODULES[name].app.test_client().get("/health").get_json()
    assert body["uptime_seconds"] >= 0 and body["chaos"] is None

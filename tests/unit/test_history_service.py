"""Unit tests for history-service that don't need PostgreSQL (the smoke test covers the database)."""
import pytest

from service_loader import load_service

module = load_service("history-service")
client = module.app.test_client()


def test_health_needs_no_database():
    body = client.get("/health").get_json()
    assert body["service"] == "history-service" and body["status"] == "ok"


def test_ready_reports_the_database_is_down():
    response = client.get("/ready")            # DB_HOST/DB_PORT point at a port where nothing listens
    assert response.status_code == 503
    assert response.get_json()["database"] == "unreachable"


def test_password_from_docker_secret_file(tmp_path, monkeypatch):
    secret = tmp_path / "db_password"
    secret.write_text("s3cret-from-file\r\n")     # a file saved on Windows ends with \r\n
    monkeypatch.setenv("DB_PASSWORD_FILE", str(secret))
    assert module.read_password() == "s3cret-from-file"


def test_password_from_environment(monkeypatch):
    monkeypatch.delenv("DB_PASSWORD_FILE", raising=False)
    monkeypatch.setenv("DB_PASSWORD", "from-env")
    assert module.read_password() == "from-env"


def test_missing_secret_file_stops_the_service(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PASSWORD_FILE", str(tmp_path / "missing"))
    with pytest.raises(SystemExit):
        module.read_password()


def test_bad_records_are_rejected_before_touching_the_database():
    response = client.post("/records", json={"tool": "nope", "summary": "x"})
    assert response.status_code == 400 and response.get_json()["field"] == "tool"
    response = client.post("/records", data="not json", content_type="text/plain")
    assert response.status_code == 400

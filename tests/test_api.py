import pytest
from fastapi.testclient import TestClient

from app import db, ratelimit
from app.main import app

VALID = {
    "name": "Анна",
    "phone": "+7 900 123-45-67",
    "service": "Педикюр",
    "consent": True,
    "website": "",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Свежая база на каждый тест и никаких настоящих токенов из .env
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    for var in ("ADMIN_PASSWORD", "BOT_TOKEN", "CHAT_ID"):
        monkeypatch.delenv(var, raising=False)
    ratelimit.reset()
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_services_list(client):
    data = client.get("/api/services").json()
    assert data and "group" in data[0] and data[0]["items"]


def test_index_and_security_headers(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "default-src 'self'" in res.headers["content-security-policy"]
    assert res.headers["x-content-type-options"] == "nosniff"


def test_create_lead_saves_normalized_phone(client):
    res = client.post("/api/lead", json=VALID)
    assert res.status_code == 200 and res.json() == {"ok": True}
    leads = db.list_leads()
    assert len(leads) == 1
    assert leads[0]["phone"] == "79001234567"


@pytest.mark.parametrize(
    "patch",
    [
        {"consent": False},
        {"service": "Несуществующая услуга"},
        {"phone": "123"},
        {"name": "А"},
    ],
)
def test_rejects_invalid_data(client, patch):
    res = client.post("/api/lead", json={**VALID, **patch})
    assert res.status_code == 422
    assert db.list_leads() == []


def test_honeypot_is_not_saved(client):
    res = client.post("/api/lead", json={**VALID, "website": "http://spam.example"})
    assert res.status_code == 200
    assert db.list_leads() == []


def test_rate_limit(client):
    for _ in range(5):
        assert client.post("/api/lead", json=VALID).status_code == 200
    assert client.post("/api/lead", json=VALID).status_code == 429


def test_admin_disabled_without_password(client):
    assert client.get("/admin").status_code == 404


def test_admin_requires_auth_and_escapes_html(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    client.post("/api/lead", json={**VALID, "name": "<b>Хакер</b>"})
    assert client.get("/admin").status_code == 401
    assert client.get("/admin", auth=("admin", "wrong")).status_code == 401
    page = client.get("/admin", auth=("admin", "secret"))
    assert page.status_code == 200
    assert "&lt;b&gt;" in page.text and "<b>Хакер" not in page.text

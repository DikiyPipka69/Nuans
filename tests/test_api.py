import pytest
from fastapi.testclient import TestClient

from app import db, formtoken, ratelimit
from app.main import app

PASSWORD = "secret-password-123"
AUTH = ("admin", PASSWORD)
ENDPOINT = "/api/services"  # любой публичный GET-маршрут
LEAD = {"name": "Анна", "phone": "+7 900 123-45-67", "service": "Педикюр", "consent": True, "website": ""}


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Свежая база на каждый тест, известный пароль админки, без ожидания перед отправкой формы
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("FORM_MIN_AGE", "0")
    monkeypatch.delenv("RENDER", raising=False)
    ratelimit.reset()
    formtoken.reset()
    with TestClient(app) as c:
        yield c


def send(client, **patch):
    """Отправляет заявку так, как это делает страница: сначала токен, потом форма."""
    token = client.get("/api/form-token").json()["token"]
    return client.post("/api/lead", json={**LEAD, "token": token, **patch})


# ---------- общее: доступность и защитные заголовки ----------
def test_health_get_and_head(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.head("/api/health").status_code == 200


def test_index_get_and_head(client):
    assert client.get("/").status_code == 200
    assert client.head("/").status_code == 200


def test_security_headers(client):
    res = client.get("/")
    for name in (
        "content-security-policy", "x-frame-options", "x-content-type-options",
        "permissions-policy", "cross-origin-opener-policy", "cross-origin-resource-policy",
    ):
        assert name in res.headers, name
    assert "strict-transport-security" not in res.headers  # по обычному http HSTS не нужен


def test_hsts_over_https(client):
    with TestClient(app, base_url="https://testserver") as secure:
        assert "max-age" in secure.get("/").headers["strict-transport-security"]


def test_api_responses_are_not_cached(client):
    assert client.get(ENDPOINT).headers["cache-control"] == "no-store"


def test_no_cors_headers(client):
    res = client.get(ENDPOINT, headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers


# ---------- общее: защита от перегрузки ----------
def test_global_rate_limit(client, monkeypatch):
    monkeypatch.setattr("app.main.RATE_LIMIT_PER_MIN", 5)
    codes = [client.get(ENDPOINT).status_code for _ in range(7)]
    assert codes == [200] * 5 + [429] * 2
    blocked = client.get(ENDPOINT)
    assert blocked.headers["retry-after"] == "60"
    assert "content-security-policy" in blocked.headers  # защитные заголовки есть и у отказов
    assert client.get("/api/health").status_code == 200  # проверка здоровья лимитом не ограничивается


def test_oversized_body_is_rejected(client):
    res = client.post("/api/lead", content=b"x" * 20000, headers={"Content-Type": "application/json"})
    assert res.status_code == 413
    assert db.list_leads() == []


# ---------- общее: токен формы ----------
def test_form_token_endpoint(client):
    assert client.get("/api/form-token").json()["token"].count(".") == 2


def test_form_token_endpoint_is_rate_limited(client):
    codes = [client.get("/api/form-token").status_code for _ in range(32)]
    assert codes[:30] == [200] * 30 and codes[30:] == [429, 429]


def test_lead_requires_token(client):
    assert client.post("/api/lead", json=LEAD).status_code == 422


@pytest.mark.parametrize("bad", ["garbage-token-value", "1234567.89abcdef.abc", "x" * 50])
def test_lead_rejects_forged_token(client, bad):
    assert send(client, token=bad).status_code == 400
    assert db.list_leads() == []


def test_token_is_single_use(client):
    token = client.get("/api/form-token").json()["token"]
    assert client.post("/api/lead", json={**LEAD, "token": token}).status_code == 200
    assert client.post("/api/lead", json={**LEAD, "token": token}).status_code == 400


def test_form_submitted_too_fast_is_rejected(client, monkeypatch):
    monkeypatch.setenv("FORM_MIN_AGE", "60")
    assert send(client).status_code == 400
    assert db.list_leads() == []


# ---------- общее: заявки ----------
def test_lead_is_saved_with_clean_phone(client):
    assert send(client).status_code == 200
    lead = db.list_leads()[0]
    assert lead["phone"] == "79001234567" and lead["name"] == "Анна"


@pytest.mark.parametrize("patch", [{"consent": False}, {"phone": "123"}, {"name": "А"}, {"name": "А" * 61}, {"service": "Нет такой"}])
def test_invalid_lead_is_rejected(client, patch):
    assert send(client, **patch).status_code == 422
    assert db.list_leads() == []


def test_honeypot_is_not_saved(client):
    assert send(client, website="http://spam.example").status_code == 200
    assert db.list_leads() == []


@pytest.mark.parametrize("name", ["http://spam.ru", "Купи www.spam.ru"])
def test_spam_in_name_is_not_saved(client, name):
    assert send(client, name=name).status_code == 200  # боту отвечаем «ок», но ничего не сохраняем
    assert db.list_leads() == []


def test_invisible_characters_are_removed(client):
    assert send(client, name="Анна\u202e\u200b").status_code == 200
    assert db.list_leads()[0]["name"] == "Анна"


def test_duplicate_lead_is_ignored(client):
    assert send(client).status_code == 200
    assert send(client, name="Анна Другая").status_code == 200  # тот же телефон: считается повтором
    assert len(db.list_leads()) == 1


def test_lead_rate_limit(client):
    for i in range(5):
        assert send(client, phone=f"+7 900 000-00-{i:02d}").status_code == 200
    assert send(client, phone="+7 900 000-00-99").status_code == 429


# ---------- общее: админка ----------
def test_admin_is_disabled_without_password(client, monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD")
    assert client.get("/admin").status_code == 404


def test_weak_password_is_refused_on_production(client, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("ADMIN_PASSWORD", "short")
    assert client.get("/admin", auth=("admin", "short")).status_code == 404
    monkeypatch.setenv("ADMIN_PASSWORD", "a-long-unique-passphrase-2026")
    assert client.get("/admin", auth=("admin", "a-long-unique-passphrase-2026")).status_code == 200


def test_admin_requires_correct_credentials(client):
    assert client.get("/admin").status_code == 401
    assert client.get("/admin", auth=("admin", "wrong")).status_code == 401
    assert client.get("/admin", auth=("root", PASSWORD)).status_code == 401
    assert client.get("/admin", auth=AUTH).status_code == 200


def test_admin_locks_out_after_failed_attempts(client):
    for _ in range(10):
        assert client.get("/admin", auth=("admin", "wrong")).status_code == 401
    # после десяти неудач вход закрыт даже с правильным паролем
    assert client.get("/admin", auth=AUTH).status_code == 429


# ---------- общее: страницы ошибок ----------
def test_unknown_page_gives_html_404(client):
    res = client.get("/no-such-page")
    assert res.status_code == 404
    assert "text/html" in res.headers["content-type"]


def test_unknown_api_route_gives_json_404(client):
    res = client.get("/api/no-such-route")
    assert res.status_code == 404
    assert res.json() == {"detail": "Not Found"}


# ---------- Нюанс ----------
def test_services_api(client):
    data = client.get("/api/services").json()
    assert data and data[0]["items"]


def test_admin_escapes_html(client):
    send(client, name="<b>Хакер</b>")
    page = client.get("/admin", auth=AUTH)
    assert page.status_code == 200
    assert "&lt;b&gt;" in page.text and "<b>Хакер" not in page.text

"""Демо-сайт студии красоты «Нюанс»: FastAPI + SQLite."""
import html
import json
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import db, formtoken, ratelimit, security

load_dotenv()  # читает .env при локальном запуске; на Render переменные задаются в панели

log = logging.getLogger("app.security")

BASE_DIR = Path(__file__).resolve().parent.parent
SERVICES = json.loads((BASE_DIR / "app" / "services.json").read_text("utf-8"))
SERVICE_NAMES = {item["name"] for group in SERVICES for item in group["items"]}
DOCS_ENABLED = bool(os.environ.get("ENABLE_DOCS"))
BAD_DATA = "Проверьте введённые данные"
STALE_FORM = "Форма устарела или отправлена слишком быстро. Подождите секунду и нажмите «Отправить» ещё раз."
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "240"))  # запросов в минуту с одного IP
ADMIN_FAIL_LIMIT = 10     # столько неудачных входов подряд...
ADMIN_FAIL_WINDOW = 900   # ...за 15 минут закрывают вход с этого адреса


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def production() -> bool:
    return bool(os.environ.get("RENDER"))  # Render сам задаёт эту переменную


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    password = os.environ.get("ADMIN_PASSWORD")
    problem = security.admin_password_problem(password, production()) if password else None
    if problem:
        log.error("ADMIN_PASSWORD не подходит для боевого сервера (%s): админка отключена", problem)
    yield


app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url=None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)
app.add_middleware(security.BodyLimitMiddleware, max_bytes=security.MAX_BODY)


@app.middleware("http")
async def guard(request: Request, call_next):
    """Общий лимит запросов с одного IP и защитные заголовки на каждый ответ."""
    path = request.url.path
    ip = client_ip(request)
    if path != "/api/health" and not ratelimit.allow(f"req:{ip}", RATE_LIMIT_PER_MIN, 60):
        log.warning("слишком много запросов ip=%s path=%s", ip, path)
        response = JSONResponse(
            {"detail": "Слишком много запросов, подождите минуту"},
            status_code=429,
            headers={"Retry-After": "60"},
        )
    else:
        response = await call_next(request)
    for name, value in security.response_headers(path, request.url.scheme == "https").items():
        response.headers[name] = value
    return response


# Необязательно: пускать только запросы на свои домены (ALLOWED_HOSTS=example.com,www.example.com)
_hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
if _hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_hosts)


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": BAD_DATA})


@app.exception_handler(StarletteHTTPException)
async def on_http_error(request: Request, exc: StarletteHTTPException):
    # Для страниц сайта показываем красивую 404, для API оставляем JSON
    if exc.status_code == 404 and not request.url.path.startswith("/api"):
        return FileResponse(BASE_DIR / "static" / "404.html", status_code=404)
    return await http_exception_handler(request, exc)


class Lead(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=60)
    phone: str = Field(max_length=30)
    service: str = Field(max_length=100)
    consent: bool
    website: str = Field(default="", max_length=200)  # ловушка для ботов, у людей пусто
    token: str = Field(min_length=10, max_length=100)  # одноразовый токен из /api/form-token

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = re.sub(r"\s+", " ", security.clean_text(value))
        if len(value) < 2:
            raise ValueError("слишком короткое имя")
        return value

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if not 10 <= len(digits) <= 15:
            raise ValueError("некорректный телефон")
        return digits

    @field_validator("service")
    @classmethod
    def known_service(cls, value: str) -> str:
        if value not in SERVICE_NAMES:
            raise ValueError("неизвестная услуга")
        return value

    @field_validator("consent")
    @classmethod
    def need_consent(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("нужно согласие")
        return value


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok"}


@app.get("/api/services")
def services():
    return SERVICES


@app.get("/api/form-token")
def form_token(request: Request):
    if not ratelimit.allow(f"tok:{client_ip(request)}", 30, 60):
        raise HTTPException(status_code=429, detail="Слишком много запросов, подождите минуту")
    return {"token": formtoken.issue()}


@app.post("/api/lead")
def create_lead(lead: Lead, request: Request):
    ip = client_ip(request)
    if lead.website:  # заполнил бот: делаем вид, что всё хорошо, ничего не сохраняя
        log.info("ловушка для ботов сработала ip=%s", ip)
        return {"ok": True}
    status = formtoken.verify(lead.token)
    if status != "ok":
        log.info("токен формы отклонён (%s) ip=%s", status, ip)
        raise HTTPException(status_code=400, detail=STALE_FORM)
    if security.looks_like_spam(lead.name):
        log.info("спам в имени ip=%s", ip)
        return {"ok": True}
    if not ratelimit.allow(f"lead:{ip}"):
        log.warning("лимит заявок ip=%s", ip)
        raise HTTPException(status_code=429, detail="Слишком много заявок, попробуйте позже")
    if db.has_recent_lead(lead.phone):  # повтор: двойной клик или спам
        return {"ok": True}
    db.add_lead(lead.name, lead.phone, lead.service)
    return {"ok": True}


basic = HTTPBasic(auto_error=False)


def admin_auth(request: Request, creds: HTTPBasicCredentials | None = Depends(basic)) -> None:
    password = os.environ.get("ADMIN_PASSWORD")
    if not password or security.admin_password_problem(password, production()):
        raise HTTPException(status_code=404)  # админка выключена: пароля нет или он слабый
    ip = client_ip(request)
    fail_key = f"admin-fail:{ip}"
    if ratelimit.count(fail_key, ADMIN_FAIL_WINDOW) >= ADMIN_FAIL_LIMIT:
        raise HTTPException(status_code=429, detail="Слишком много неудачных попыток, попробуйте позже")
    ok = (
        creds is not None
        and secrets.compare_digest(creds.username.encode(), b"admin")
        and secrets.compare_digest(creds.password.encode(), password.encode())
    )
    if not ok:
        if creds is not None:  # первый запрос браузера без пароля неудачей не считаем
            ratelimit.hit(fail_key)
            log.warning("неудачный вход в админку ip=%s", ip)
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})


@app.get("/admin", response_class=HTMLResponse, dependencies=[Depends(admin_auth)])
def admin():
    esc = html.escape
    rows = "".join(
        "<tr>"
        f"<td>{lead['id']}</td>"
        f"<td>{esc(lead['created_at'])}</td>"
        f"<td>{esc(lead['name'])}</td>"
        f"<td>{esc(lead['phone'])}</td>"
        f"<td>{esc(lead['service'])}</td>"
        "</tr>"
        for lead in db.list_leads()
    ) or '<tr><td colspan="5">Заявок пока нет</td></tr>'
    page = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Заявки</title>
<link rel="stylesheet" href="/static/css/style.css"></head>
<body><main class="wrap admin"><h1>Заявки</h1>
<div class="tablewrap"><table>
<thead><tr><th>№</th><th>Время (UTC)</th><th>Имя</th><th>Телефон</th><th>Услуга</th></tr></thead>
<tbody>{rows}</tbody></table></div></main></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

"""Демо-сайт студии красоты «Нюанс»: FastAPI + SQLite + Telegram."""
import html
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import db, ratelimit, telegram

load_dotenv()  # читает .env при локальном запуске; на Render переменные задаются в панели

BASE_DIR = Path(__file__).resolve().parent.parent
SERVICES = json.loads((BASE_DIR / "app" / "services.json").read_text("utf-8"))
SERVICE_NAMES = {item["name"] for group in SERVICES for item in group["items"]}
DOCS_ENABLED = bool(os.environ.get("ENABLE_DOCS"))
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

CSP = (
    "default-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    yield


app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url=None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path not in DOCS_PATHS:  # Swagger грузит скрипты с CDN
        response.headers["Content-Security-Policy"] = CSP
    return response


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "Проверьте введённые данные"})


class Lead(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=60)
    phone: str = Field(max_length=30)
    service: str = Field(max_length=100)
    consent: bool
    website: str = Field(default="", max_length=200)  # ловушка для ботов, у людей пусто

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


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/services")
def services():
    return SERVICES


@app.post("/api/lead")
def create_lead(lead: Lead, request: Request, background: BackgroundTasks):
    if lead.website:  # заполнил бот: делаем вид, что всё хорошо, ничего не сохраняя
        return {"ok": True}
    ip = request.client.host if request.client else "unknown"
    if not ratelimit.allow(ip):
        raise HTTPException(status_code=429, detail="Слишком много заявок, попробуйте позже")
    db.add_lead(lead.name, lead.phone, lead.service)
    background.add_task(telegram.notify, lead.name, lead.phone, lead.service)
    return {"ok": True}


security = HTTPBasic(auto_error=False)


def admin_auth(creds: HTTPBasicCredentials | None = Depends(security)) -> None:
    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        raise HTTPException(status_code=404)  # админка выключена, пока не задан пароль
    ok = (
        creds is not None
        and secrets.compare_digest(creds.username.encode(), b"admin")
        and secrets.compare_digest(creds.password.encode(), password.encode())
    )
    if not ok:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})


@app.get("/admin", response_class=HTMLResponse, dependencies=[Depends(admin_auth)])
def admin():
    rows = "".join(
        "<tr>"
        f"<td>{lead['id']}</td>"
        f"<td>{html.escape(lead['created_at'])}</td>"
        f"<td>{html.escape(lead['name'])}</td>"
        f"<td>{html.escape(lead['phone'])}</td>"
        f"<td>{html.escape(lead['service'])}</td>"
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


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

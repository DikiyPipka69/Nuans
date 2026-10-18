# Нюанс: демо-сайт студии красоты

Учебный проект для портфолио: сайт на чистом HTML/CSS/JS и бэкенд на FastAPI.
Бренд, мастера и контакты вымышлены.

## Что умеет

- Страницы: главная, услуги и цены, мастера, контакты, политика конфиденциальности.
- Цены лежат в одном файле `app/services.json`. Меняете цену там, и она обновляется на сайте и в форме.
- Форма записи отправляет заявку на `POST /api/lead`: проверка данных, ограничение частоты (5 заявок в час с одного IP), ловушка для ботов, сохранение в SQLite, уведомление в Telegram.
- Закрытая страница `/admin` со списком заявок (логин `admin`, пароль из `ADMIN_PASSWORD`).
- Защитные заголовки (CSP и другие), экранирование данных в админке.

## Структура

```
nuance-demo/
├── app/
│   ├── main.py          # маршруты, проверка данных, админка
│   ├── db.py            # SQLite
│   ├── telegram.py      # уведомления в Telegram
│   ├── ratelimit.py     # ограничение частоты
│   └── services.json
├── static/
│   ├── index.html
│   ├── css/style.css
│   └── js/main.js
├── tests/test_api.py    # автотесты API (запуск: pytest)
├── render.yaml          # настройка деплоя на Render
├── requirements.txt
└── .env.example         # образец настроек, копируется в .env
```

## Запуск у себя (VS Code)

Нужен Python 3.12 или новее.

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -r requirements-dev.txt
cp .env.example .env          # Windows: copy .env.example .env
uvicorn app.main:app --reload
```

Откройте http://127.0.0.1:8000. Документация API: http://127.0.0.1:8000/docs
(работает при `ENABLE_DOCS=1` в `.env`).

Тесты: `pytest`

## Telegram-уведомления (по желанию)

1. В Telegram напишите `@BotFather`, команда `/newbot`, получите токен.
2. Напишите своему боту любое сообщение.
3. Узнайте свой chat id (например, через бота `@userinfobot`).
4. Впишите `BOT_TOKEN` и `CHAT_ID` в `.env` (локально) или в переменные окружения Render.

Токен нельзя выкладывать в GitHub и показывать в скриншотах.

## GitHub

```bash
git init
git add .
git commit -m "Первая версия демо-сайта"
git branch -M main
git remote add origin https://github.com/ВАШ_ЛОГИН/nuance-demo.git
git push -u origin main
```

Репозиторий сначала создайте на github.com (пустой, без README). Перед `git add` убедитесь, что файла `.env` нет в списке `git status`: он должен быть в `.gitignore`.

## Деплой на Render

**Через Blueprint (проще):** в Render нажмите New → Blueprint, выберите репозиторий. Render прочитает `render.yaml` и спросит значения `ADMIN_PASSWORD`, `BOT_TOKEN`, `CHAT_ID`.

**Вручную:** New → Web Service, репозиторий, затем:
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`
- Переменные окружения: те же, что в `.env.example`.

Если сборка ругается на версию Python, поменяйте `PYTHON_VERSION` в `render.yaml` на доступную.

### Ограничения бесплатного тарифа Render

- Сервис засыпает после 15 минут без запросов, первый заход после паузы грузится до минуты.
- Файловая система не сохраняется: заявки в SQLite пропадают при перезапуске и новом деплое. Для демо это нормально, для клиента нужна постоянная база.
- Свой домен на бесплатном тарифе не подключить.

## Важно про данные

В демо не вводите реальные имена и телефоны. Для боевого сайта с российскими клиентами понадобятся: политика конфиденциальности под конкретную компанию, хранение персональных данных на серверах в РФ (требование 152-ФЗ), постоянная база. Эти вопросы мы разбираем отдельно перед первым заказом, и юристу текст политики лучше показать.

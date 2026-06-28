# Cyber Bonus

Cyber Bonus — это SaaS-модуль для компьютерных клубов, который расширяет возможности основной системы управления клубом за счет геймификации, аналитики и Telegram-интеграции.

Проект ориентирован на работу с данными клуба: гостями, сессиями, операциями, заданиями и игровыми механиками вроде колеса фортуны.

---

## Что умеет проект

### Кабинет владельца клуба
- дашборд с основными метриками
- настройки клуба
- подключение LANGAME API
- ручной запуск синхронизации

### Гостевой кабинет
- авторизация через Telegram
- просмотр доступных заданий
- отображение прогресса по заданиям
- просмотр жетонов
- участие в механике колеса фортуны

### Геймификация
- настраиваемые задания
- прогресс по заданиям на основе данных сессий
- колесо фортуны с призами, весами и стоимостью прокрутки
- логика жетонов за посещения

### Синхронизация данных
- гости
- сессии
- операции
- initial sync и incremental sync через отдельные скрипты

---

## Технологии

- Python
- Flask
- MySQL
- SQLAlchemy
- PyMySQL
- Alembic
- Jinja2
- HTML / CSS
- Telegram Bot API
- LANGAME API

---

## Актуальная структура проекта

```text
clubmodule/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── core.py
│   │
│   ├── routes/
│   │   ├── public.py
│   │   ├── auth.py
│   │   ├── guest.py
│   │   ├── sync.py
│   │   ├── dashboard.py
│   │   ├── settings.py
│   │   ├── missions.py
│   │   ├── wheel.py
│   │   └── clubs.py
│   │
│   ├── services/
│   │   ├── guest_auth.py
│   │   ├── clubs.py
│   │   ├── dashboard.py
│   │   ├── missions.py
│   │   └── wheel.py
│   │
│   ├── templates/
│   └── static/
│
├── scripts/
│   ├── sync_guests.py
│   ├── sync_guests_incremental.py
│   ├── sync_sessions_initial.py
│   ├── sync_sessions_incremental.py
│   ├── sync_operations_initial.py
│   └── sync_operations_incremental.py
│
├── alembic/
├── .env.example
├── pyproject.toml
└── README.md
```

---

## Коммерческая готовность

Для доведения проекта до стабильной продуктовой версии заведены рабочие документы:

- [Product maturity roadmap](docs/PRODUCT_MATURITY_ROADMAP.md) — план доведения продукта до уровня 9/10.
- [Production readiness checklist](docs/PRODUCTION_READINESS_CHECKLIST.md) — проверка перед подключением платного клуба.
- [Pilot onboarding checklist](docs/PILOT_ONBOARDING_CHECKLIST.md) — чеклист ручного запуска первых пилотных клубов.
- [Database migrations](docs/DATABASE_MIGRATIONS.md) — как применять и добавлять миграции базы.
- [Safe rollout plan](docs/SAFE_ROLLOUT_PLAN.md) — как выпускать изменения, не ломая текущую рабочую версию.

В production-окружении обязательно указывать `APP_ENV=production` и все критичные переменные из `.env.example`.

Перед запуском новой версии в production примените миграции базы данных:

```bash
python3 scripts/migrate.py
```

Локальные smoke-проверки:

```bash
pip install -r requirements-dev.txt
pytest
```

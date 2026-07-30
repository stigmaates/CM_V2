# ClubModule / Cyber Bonus

ClubModule — веб-модуль для компьютерных клубов с аналитикой, CRM-механиками, геймификацией, Telegram-интеграцией и синхронизацией данных из LANGAME.

Проект работает с гостями клуба, игровыми сессиями, операциями, заданиями, жетонами, колесом фортуны, КБ-бонусами, рассылками и автоматическими сценариями.

---

## Основные возможности

### Кабинет владельца клуба

- Дашборд с ключевыми метриками клуба.
- Периоды аналитики: 7 / 30 / 90 дней и «за всё время».
- CRM-аналитика по гостям.
- Управление рассылками и авторассылками.
- Управление заданиями, жетонами, бонусами и колесом фортуны.
- Настройки клуба, Telegram-чатов и социальных ссылок.
- Ручной запуск initial/incremental-синхронизаций.

### Гостевой кабинет

- Авторизация гостя через Telegram.
- Просмотр персонального дашборда.
- Прогресс по заданиям.
- Баланс жетонов.
- Колесо фортуны.
- История призов и переводов КБ.
- Перевод КБ-бонусов с уведомлением админов в Telegram.

### Telegram-интеграция

В проекте используются два Telegram-бота:

1. **Гостевой бот** — авторизация гостей и взаимодействие с гостевым кабинетом.
2. **Админский / worker-бот** — уведомления администраторам, заявки на перевод КБ и inline-кнопки вроде «Бонусы зачислены».

Важно: callback-кнопки админского бота должны обрабатываться отдельным процессом `run_admin_bot.py`.

---

## Технологии

- Python
- Flask
- MySQL
- PyMySQL
- python-dotenv
- python-telegram-bot
- httpx
- Jinja2
- HTML / CSS / JavaScript
- systemd
- cron
- LANGAME API

---

## Структура проекта

```text
CM_V2/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── core.py
│   ├── routes/
│   │   ├── admin/
│   │   ├── owner/
│   │   ├── guest/
│   │   └── common/
│   ├── services/
│   │   ├── clubs.py
│   │   ├── cm_bonuses.py
│   │   ├── dashboard.py
│   │   ├── first_visit_survey.py
│   │   ├── guest_auth.py
│   │   ├── mailing.py
│   │   ├── missions.py
│   │   ├── pc_heatmap.py
│   │   ├── prize_claims.py
│   │   ├── system_status.py
│   │   └── wheel.py
│   ├── templates/
│   └── static/
│
├── bot/
│   ├── main.py          # гостевой Telegram-бот
│   └── admin_main.py    # админский Telegram-бот / worker-бот
│
├── scripts/
│   ├── process_mailings.py
│   ├── process_auto_mailings.py
│   ├── rebuild_user_portrait.py
│   ├── sync_guests.py
│   ├── sync_guests_incremental.py
│   ├── sync_sessions_initial.py
│   ├── sync_sessions_incremental.py
│   ├── sync_operations_initial.py
│   ├── sync_operations_incremental.py
│   ├── sync_balance_topups_initial.py
│   └── sync_balance_topups_incremental.py
│
├── run.py               # запуск Flask-приложения
├── run_bot.py           # запуск гостевого Telegram-бота
├── run_admin_bot.py     # запуск админского Telegram-бота
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Коммерческая готовность

Для доведения проекта до стабильной продуктовой версии заведены рабочие документы:

- [Product maturity roadmap](docs/PRODUCT_MATURITY_ROADMAP.md) — план доведения продукта до уровня 9/10.
- [Production readiness checklist](docs/PRODUCTION_READINESS_CHECKLIST.md) — проверка перед подключением платного клуба.
- [Club onboarding runbook](docs/CLUB_ONBOARDING_RUNBOOK.md) — пошаговое подключение нового клуба.
- [Pilot onboarding checklist](docs/PILOT_ONBOARDING_CHECKLIST.md) — чеклист ручного запуска первых пилотных клубов.
- [Database migrations](docs/DATABASE_MIGRATIONS.md) — как применять и добавлять миграции базы.
- [Safe rollout plan](docs/SAFE_ROLLOUT_PLAN.md) — как выпускать изменения, не ломая текущую рабочую версию.
- [Backup and restore](docs/BACKUP_RESTORE.md) — как создавать и проверять резервные копии.
- [Deployment runbook](docs/DEPLOYMENT_RUNBOOK.md) — staging/production-регламент релиза.
- [systemd service templates](docs/SYSTEMD_SERVICES.md) — шаблоны сервисов и таймеров.
- [Nginx template](docs/NGINX_TEMPLATE.md) — шаблон reverse proxy, static и uploads.
- [Staging smoke tests](docs/STAGING_SMOKE_TESTS.md) — быстрые проверки после деплоя.
- [Release candidate checklist](docs/RELEASE_CANDIDATE_CHECKLIST.md) — финальная проверка перед релизом.
- [Stage server runbook](docs/STAGE_SERVER_RUNBOOK.md) — инструкции для текущего stage-сервера.

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

Проверка окружения перед staging/production:

```bash
python3 scripts/check_environment.py --env-file .env
```

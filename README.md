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
│   └── sync_operations_incremental.py
│
├── run.py               # запуск Flask-приложения
├── run_bot.py           # запуск гостевого Telegram-бота
├── run_admin_bot.py     # запуск админского Telegram-бота
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```


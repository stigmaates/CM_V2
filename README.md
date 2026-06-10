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

---

## Переменные окружения

Создать файл `.env` на основе `.env.example`.

```env
DB_HOST=
DB_PORT=3306
DB_USER=
DB_PASSWORD=
DB_NAME=

SECRET_KEY=

BOT_TOKEN=
CM_BONUS_BOT_TOKEN=
CM_BONUS_ADMIN_CHAT_ID=

TG_PROXY_URL=
AUTO_MAILING_TIMEZONE=Europe/Moscow
```

### Что означает каждая переменная

| Переменная | Назначение |
|---|---|
| `DB_HOST` | Хост MySQL |
| `DB_PORT` | Порт MySQL, обычно `3306` |
| `DB_USER` | Пользователь MySQL |
| `DB_PASSWORD` | Пароль MySQL |
| `DB_NAME` | Имя базы данных |
| `SECRET_KEY` | Flask secret key |
| `BOT_TOKEN` | Токен гостевого Telegram-бота |
| `CM_BONUS_BOT_TOKEN` | Токен админского / worker-бота |
| `CM_BONUS_ADMIN_CHAT_ID` | ID админского чата для заявок КБ |
| `TG_PROXY_URL` | Прокси для Telegram, если нужен |
| `AUTO_MAILING_TIMEZONE` | Таймзона авторассылок |

Не коммитить `.env` в Git.

---

## Локальный запуск

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Запуск веб-приложения:

```bash
python run.py
```

Запуск гостевого Telegram-бота:

```bash
PYTHONPATH=. python run_bot.py
```

Запуск админского Telegram-бота:

```bash
PYTHONPATH=. python run_admin_bot.py
```

---

## Продакшен на сервере

Основная рабочая папка на сервере:

```bash
/root/cm_v2/CM_V2
```

Виртуальное окружение:

```bash
/root/cm_v2/CM_V2/venv
```

---

## systemd-сервисы

В продакшене должны работать минимум три сервиса:

```text
clubmodule.service             # Flask-приложение
clubmodule-bot.service         # гостевой Telegram-бот
clubmodule-admin-bot.service   # админский Telegram-бот / worker-бот
```

### Flask-приложение

Пример сервиса:

```ini
[Unit]
Description=ClubModule Flask App
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=/root/cm_v2/CM_V2
Environment="PYTHONPATH=."
Environment="PATH=/root/cm_v2/CM_V2/venv/bin"
ExecStart=/root/cm_v2/CM_V2/venv/bin/gunicorn --timeout 300 -w 2 -b 127.0.0.1:8000 run:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Гостевой Telegram-бот

```ini
[Unit]
Description=ClubModule Telegram Bot
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=/root/cm_v2/CM_V2
Environment="PYTHONPATH=."
Environment="PATH=/root/cm_v2/CM_V2/venv/bin"
ExecStart=/root/cm_v2/CM_V2/venv/bin/python /root/cm_v2/CM_V2/run_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Админский Telegram-бот

```ini
[Unit]
Description=ClubModule Admin Telegram Bot
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=/root/cm_v2/CM_V2
Environment="PYTHONPATH=."
Environment="PATH=/root/cm_v2/CM_V2/venv/bin"
ExecStart=/root/cm_v2/CM_V2/venv/bin/python /root/cm_v2/CM_V2/run_admin_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

После изменения service-файлов:

```bash
systemctl daemon-reload
systemctl restart clubmodule.service
systemctl restart clubmodule-bot.service
systemctl restart clubmodule-admin-bot.service
```

Проверка:

```bash
systemctl status clubmodule.service
systemctl status clubmodule-bot.service
systemctl status clubmodule-admin-bot.service
```

Логи:

```bash
journalctl -u clubmodule.service -n 100 --no-pager
journalctl -u clubmodule-bot.service -n 100 --no-pager
journalctl -u clubmodule-admin-bot.service -n 100 --no-pager
```

Логи в реальном времени:

```bash
journalctl -u clubmodule.service -f
journalctl -u clubmodule-bot.service -f
journalctl -u clubmodule-admin-bot.service -f
```

---

## Cron-задачи

В проекте используются cron-задачи для рассылок, авторассылок, синхронизаций и пересборки портрета гостя.

Пример актуального crontab:

```cron
* * * * * cd /root/cm_v2/CM_V2 && flock -n /tmp/cm_process_mailings.lock -c 'PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python scripts/process_mailings.py' >> /root/cm_v2/CM_V2/logs/process_mailings.log 2>&1

*/5 * * * * cd /root/cm_v2/CM_V2 && flock -n /tmp/cm_process_auto_mailings.lock -c 'PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python scripts/process_auto_mailings.py' >> /root/cm_v2/CM_V2/logs/process_auto_mailings.log 2>&1

*/10 * * * * cd /root/cm_v2/CM_V2 && flock -n /tmp/cm_sync_guests.lock -c 'PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python scripts/sync_guests_incremental.py' >> /root/cm_v2/CM_V2/logs/sync_guests_incremental.log 2>&1

* * * * * cd /root/cm_v2/CM_V2 && flock -n /tmp/cm_sync_sessions.lock -c 'PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python scripts/sync_sessions_incremental.py' >> /root/cm_v2/CM_V2/logs/sync_sessions_incremental.log 2>&1

* * * * * cd /root/cm_v2/CM_V2 && flock -n /tmp/cm_sync_operations.lock -c 'PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python scripts/sync_operations_incremental.py' >> /root/cm_v2/CM_V2/logs/sync_operations_incremental.log 2>&1

2-59/10 * * * * cd /root/cm_v2/CM_V2 && flock -n /tmp/cm_rebuild_user_portrait.lock -c 'PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python scripts/rebuild_user_portrait.py' >> /root/cm_v2/CM_V2/logs/rebuild_user_portrait.log 2>&1
```

`flock` защищает от параллельного запуска одного и того же скрипта.

Проверить crontab:

```bash
crontab -l
```

Проверить cron-сервис:

```bash
systemctl status cron
```

---

## Ручной запуск скриптов

Перейти в проект:

```bash
cd /root/cm_v2/CM_V2
```

Проверить синтаксис основных скриптов:

```bash
PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python -m py_compile \
  scripts/process_mailings.py \
  scripts/process_auto_mailings.py \
  scripts/sync_guests_incremental.py \
  scripts/sync_sessions_incremental.py \
  scripts/sync_operations_incremental.py \
  scripts/rebuild_user_portrait.py
```

Ручной запуск:

```bash
PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python scripts/process_mailings.py
PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python scripts/process_auto_mailings.py
PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python scripts/sync_guests_incremental.py
PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python scripts/sync_sessions_incremental.py
PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python scripts/sync_operations_incremental.py
PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python scripts/rebuild_user_portrait.py
```

---

## Логи проекта

Логи cron-скриптов находятся здесь:

```bash
/root/cm_v2/CM_V2/logs/
```

Посмотреть последние строки всех логов:

```bash
cd /root/cm_v2/CM_V2

for f in logs/*.log; do
  echo "==================== $f ===================="
  tail -n 20 "$f"
done
```

Найти ошибки:

```bash
cd /root/cm_v2/CM_V2

grep -Rni "Traceback\|ERROR\|OperationalError\|IntegrityError\|InterfaceError\|Lost connection\|Timeout\|Exception" logs/ | tail -n 100
```

Проверить время обновления логов:

```bash
ls -lah /root/cm_v2/CM_V2/logs/
```

---

## Мультиклубовость и ключи гостей

Важное правило проекта:

```text
guest_id не является глобально уникальным между клубами.
```

Во всех местах, где работа идёт с гостем, правильный ключ:

```text
club_id + guest_id
```

Нельзя полагаться только на `guest_id`, если запрос не ограничен конкретным клубом.

Особенно важно для:

- `guests`
- `guest_sessions`
- `operations_log`
- `user_portrait`
- `guest_wheel_spins`
- `guest_wheel_token_balances`
- `cm_bonus_balances`
- `cm_bonus_redeem_requests`
- `prize_claims`
- `guest_login_tokens`

Для таблицы `user_portrait` primary key должен быть составным:

```sql
PRIMARY KEY (club_id, guest_id)
```

Проверка индекса:

```sql
USE default_db;
SHOW INDEX FROM user_portrait;
```

---

## Полезные SQL-проверки

### Дубли гостей внутри одного клуба

```sql
USE default_db;

SELECT 
    club_id,
    guest_id,
    COUNT(*) AS cnt
FROM guests
GROUP BY club_id, guest_id
HAVING COUNT(*) > 1
ORDER BY cnt DESC, club_id, guest_id
LIMIT 100;
```

### Повторяющиеся `guest_id` между клубами

Это не ошибка, но полезно для диагностики:

```sql
SELECT 
    guest_id,
    COUNT(*) AS cnt,
    GROUP_CONCAT(club_id ORDER BY club_id) AS clubs
FROM guests
GROUP BY guest_id
HAVING COUNT(*) > 1
ORDER BY cnt DESC, guest_id
LIMIT 100;
```

### Проверить портрет гостя

```sql
SELECT 
    club_id,
    guest_id,
    total_visits,
    total_hours_all,
    avg_check_all,
    updated_at
FROM user_portrait
WHERE guest_id = 63371
ORDER BY club_id;
```

### Сравнить портрет с реальными сессиями

```sql
SELECT 
    club_id,
    guest_id,
    COUNT(*) AS sessions_count,
    MIN(date_start) AS first_session,
    MAX(date_start) AS last_session,
    ROUND(SUM(TIMESTAMPDIFF(MINUTE, date_start, date_stop)) / 60, 2) AS total_hours
FROM guest_sessions
WHERE guest_id = 63371
GROUP BY club_id, guest_id
ORDER BY club_id;
```

### Свежесть `user_portrait`

```sql
SELECT 
    COUNT(*) AS portraits_count,
    MAX(updated_at) AS last_updated
FROM user_portrait;
```

### Сводка по прокруткам колеса и визитам за последние 3 дня

```sql
SELECT
    g.club_id,
    g.guest_id,
    g.fio,
    COUNT(s.id) AS spins_count,
    GROUP_CONCAT(p.name ORDER BY s.created_at SEPARATOR '; ') AS prizes_received,
    COALESCE(v.visits_3d, 0) AS visits_last_3d
FROM guests g
JOIN guest_wheel_spins s
    ON s.club_id = g.club_id
   AND s.guest_id = g.guest_id
JOIN club_wheel_prizes p
    ON p.club_id = s.club_id
   AND p.id = s.prize_id
LEFT JOIN (
    SELECT
        club_id,
        guest_id,
        COUNT(*) AS visits_3d
    FROM guest_sessions
    WHERE date_start >= NOW() - INTERVAL 3 DAY
    GROUP BY club_id, guest_id
) v
    ON v.club_id = g.club_id
   AND v.guest_id = g.guest_id
GROUP BY
    g.club_id,
    g.guest_id,
    g.fio,
    v.visits_3d
ORDER BY spins_count DESC, g.club_id, g.fio;
```

---

## Деплой через Git

На локальной машине:

```bash
git status
git add .
git commit -m "your commit message"
git push
```

На сервере:

```bash
cd /root/cm_v2/CM_V2
git status
git pull origin main
```

Проверить синтаксис после pull:

```bash
PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python -m py_compile \
  app/services/dashboard.py \
  app/services/guest_auth.py \
  app/services/cm_bonuses.py \
  app/routes/guest/main.py \
  bot/main.py \
  bot/admin_main.py \
  run_bot.py \
  run_admin_bot.py
```

Перезапуск сервисов:

```bash
systemctl restart clubmodule.service
systemctl restart clubmodule-bot.service
systemctl restart clubmodule-admin-bot.service
```

Проверка:

```bash
systemctl status clubmodule.service
systemctl status clubmodule-bot.service
systemctl status clubmodule-admin-bot.service
```

---

## Быстрый чек-лист после деплоя

```bash
cd /root/cm_v2/CM_V2

echo "=== SERVICES ==="
systemctl is-active clubmodule.service
systemctl is-active clubmodule-bot.service
systemctl is-active clubmodule-admin-bot.service
systemctl is-active nginx
systemctl is-active cron

echo "=== RECENT WEB LOGS ==="
journalctl -u clubmodule.service -n 50 --no-pager

echo "=== RECENT GUEST BOT LOGS ==="
journalctl -u clubmodule-bot.service -n 50 --no-pager

echo "=== RECENT ADMIN BOT LOGS ==="
journalctl -u clubmodule-admin-bot.service -n 50 --no-pager

echo "=== CRON LOGS ==="
ls -lah logs/

echo "=== RECENT ERRORS ==="
grep -Rni "Traceback\|ERROR\|OperationalError\|IntegrityError\|InterfaceError\|Lost connection\|Timeout\|Exception" logs/ | tail -n 50
```

---

## Частые проблемы

### `Unexpected token '<', '<html>...' is not valid JSON`

Фронт ожидал JSON, а сервер вернул HTML-страницу ошибки. Обычно причина:

- 500 на backend;
- 404;
- редирект на login;
- timeout gunicorn.

Проверить:

```bash
journalctl -u clubmodule.service -n 100 --no-pager
```

Для долгих initial-синхронизаций у gunicorn должен быть увеличен timeout, например:

```bash
--timeout 300
```

### Кнопка «Бонусы зачислены» не реагирует

Проверить, что запущен админский бот:

```bash
systemctl status clubmodule-admin-bot.service
journalctl -u clubmodule-admin-bot.service -f
```

Callback этой кнопки обрабатывается админским ботом через `run_admin_bot.py`, а не гостевым ботом `run_bot.py`.

### `Service has more than one ExecStart=`

В systemd service-файле две строки `ExecStart=`. Нужно оставить только одну.

Проверить:

```bash
systemctl cat clubmodule-admin-bot.service
```

### `Lost connection to MySQL server during query`

Обычно временная проблема нагрузки или долгого запроса.

Проверить:

```bash
systemctl status mysql
journalctl -u mysql -n 100 --no-pager
free -h
df -h
```

### Одинаковые `guest_id` в разных клубах

Это нормально. Ошибка возникает только если код или таблица использует `guest_id` без `club_id`.

---

## Безопасность

- Не коммитить `.env`.
- Не хранить токены ботов в README или коде.
- Если токен случайно попал в чат/лог/архив — перевыпустить его через BotFather.
- Для продакшена хранить доступы только на сервере в `.env`.
- Перед изменением структуры БД делать бэкап таблицы.

Пример бэкапа таблицы:

```sql
CREATE TABLE user_portrait_backup_YYYYMMDD AS
SELECT * FROM user_portrait;
```

---

## Минимальные команды для обслуживания

```bash
cd /root/cm_v2/CM_V2

git pull origin main

PYTHONPATH=. /root/cm_v2/CM_V2/venv/bin/python -m py_compile app/services/dashboard.py

systemctl restart clubmodule.service
systemctl restart clubmodule-bot.service
systemctl restart clubmodule-admin-bot.service

journalctl -u clubmodule.service -n 100 --no-pager
journalctl -u clubmodule-bot.service -n 100 --no-pager
journalctl -u clubmodule-admin-bot.service -n 100 --no-pager
```

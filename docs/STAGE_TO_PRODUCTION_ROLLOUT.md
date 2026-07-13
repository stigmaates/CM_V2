# Stage to Production Rollout

Документ описывает безопасный перенос функциональности из stage/readiness ветки в production без копирования stage-данных, секретов и тестовой конфигурации.

## Текущее состояние веток

Актуально на момент проверки:

- production-кандидат в репозитории: `origin/main`
- активная stage/readiness ветка: `origin/product-readiness-from-stage`
- старая stage ветка: `origin/stage`

Сравнение:

- `origin/main...origin/product-readiness-from-stage`: `main` содержит 2 своих коммита, stage/readiness содержит 91 коммит сверху относительно общей истории.
- `origin/stage...origin/product-readiness-from-stage`: `origin/stage` полностью входит в `product-readiness-from-stage`; readiness ветка содержит 54 дополнительных коммита сверху.
- В `origin/main`, которых нет в readiness ветке, есть 2 README-коммита: `c3af057`, `7239bf6`.

Перед production rollout нужно решить, какая ветка является production source of truth:

- рекомендуемый вариант: `main` или отдельная `production`;
- `product-readiness-from-stage` остается веткой stage-проверки;
- перенос в production делать через merge/rebase/PR, а не копированием файлов с сервера.

## Что изменилось на stage/readiness по сравнению с main

Крупно:

- добавлены cases как бонусная механика для гостя и owner-настройки кейсов;
- переработан guest dashboard, включая cases/wheel/CM bonuses/referrals;
- переработан owner dashboard: блок кейсов, воронка, mission completions analytics, spacing;
- добавлены product-readiness инфраструктура, health/ready endpoints, release metadata;
- добавлены migrations и migration runner с dry-run;
- добавлены environment preflight и smoke HTTP checks;
- добавлены MySQL backup/restore scripts и fixes для restricted MySQL backup;
- добавлен stage refresh script from production;
- добавлены job runs, job locks, stale job markers;
- добавлены operational alerts dashboard и Telegram alerts;
- добавлены backup freshness monitoring и stage backup timer;
- добавлены admin system readiness summary, sync health, sync observability;
- добавлены admin service restart controls;
- добавлена CSRF-защита для unsafe HTTP methods;
- добавлены deploy templates для nginx/systemd;
- добавлены runbooks/checklists для release, stage, backup, onboarding;
- добавлен тестовый слой: pytest config, CI workflow и набор unit/script tests.

По diff:

- изменено/добавлено 122 файла;
- около 12k строк добавлено;
- основные новые области: `app/services/*`, `app/routes/owner/cases.py`, `migrations/`, `scripts/`, `deploy/`, `docs/`, `tests/`.

## Что нельзя переносить из stage в production

Нельзя копировать напрямую:

- `.env`;
- токены Telegram;
- пароли, proxy, API secrets;
- stage database dump целиком;
- stage backups;
- stage uploads;
- stage-only systemd units без адаптации;
- ручные backup-файлы, patch-файлы, временные файлы.

Production должен получить только:

- проверенный код;
- миграции;
- production `.env`, заполненный отдельно;
- production systemd/nginx конфигурацию, адаптированную под `/root/cm_v2/CM_V2`;
- production database backup перед миграциями.

## Production paths and services

Production:

```bash
/root/cm_v2/CM_V2
clubmodule.service
clubmodule-bot.service
```

Stage:

```bash
/root/cm_stage/CM_V2
clubmodule-stage.service
clubmodule-stage-bot.service
```

Stage команды и stage units не применять к production без проверки путей, environment files, service names и домена.

## Pre-rollout checks на stage

Перед переносом в production stage должен быть зеленым:

```bash
cd /root/cm_stage/CM_V2
git status -sb
venv/bin/python scripts/check_environment.py --env-file .env
venv/bin/python scripts/migrate.py --dry-run
venv/bin/python -m compileall -q app bot scripts migrations tests
venv/bin/python scripts/smoke_http.py --base-url <STAGE_URL>
```

Также вручную проверить:

- `/login`;
- owner dashboard;
- owner settings: wheel/cases/missions;
- guest login;
- guest dashboard;
- wheel spin;
- case opening;
- CM bonus redeem;
- admin dashboard;
- admin operational alerts;
- admin restart controls;
- backup freshness status.

## Проверка production базы до релиза

Безопасная проверка без изменения базы:

```bash
cd /root/cm_v2/CM_V2
venv/bin/python scripts/check_environment.py --env-file .env
venv/bin/python scripts/migrate.py --dry-run
```

Если вывод:

```text
No pending migrations.
```

схема production базы уже готова.

Если есть pending migrations, перед запуском нового кода нужно сделать backup и применить миграции.

## Recommended rollout flow

### 1. Подготовить release ветку

Локально или через GitHub:

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
git merge --no-ff origin/product-readiness-from-stage
```

Если `main` содержит README-коммиты, которых нет в readiness ветке, merge должен сохранить их.

После merge:

```bash
venv/bin/python -m pytest -q
venv/bin/python -m compileall -q app bot scripts migrations tests
git push origin main
```

Альтернатива: создать отдельную ветку `production-release-YYYYMMDD` и открыть PR в `main`.

### 2. Сделать production backup

На production:

```bash
cd /root/cm_v2/CM_V2
./scripts/backup_mysql.sh
```

Если production еще не содержит новый backup script, использовать текущий production backup process или временно выполнить backup командой, описанной в `docs/BACKUP_RESTORE.md`.

### 3. Подтянуть код на production

```bash
cd /root/cm_v2/CM_V2
git fetch origin
git checkout main
git pull --ff-only origin main
```

Если production использует отдельную ветку, заменить `main` на production branch.

### 4. Проверить env

```bash
venv/bin/python scripts/check_environment.py --env-file .env
```

Перед первым включением новых возможностей проверить production `.env`:

- `APP_ENV=production`;
- `SECRET_KEY` уникальный и длинный;
- `BOT_TOKEN` production бота;
- `DB_*` production базы;
- `TECH_ALERT_BOT_TOKEN` и `TECH_ALERT_CHAT_ID`, если включаем tech alerts;
- `BACKUP_MONITOR_DIRS`;
- `BACKUP_MAX_AGE_HOURS`;
- `ADMIN_SERVICE_RESTART_ENABLED`;
- `ADMIN_RESTART_SERVICES`.

Не переносить значения из stage `.env`.

### 5. Применить миграции

Сначала dry-run:

```bash
venv/bin/python scripts/migrate.py --dry-run
```

Потом настоящий запуск:

```bash
venv/bin/python scripts/migrate.py
```

### 6. Проверить код и перезапустить сервисы

```bash
venv/bin/python -m compileall -q app bot scripts migrations tests
systemctl restart clubmodule.service
systemctl restart clubmodule-bot.service
```

Если production использует отдельные worker/timer services, перезапустить их по production runbook.

### 7. Post-rollout smoke

```bash
venv/bin/python scripts/smoke_http.py --base-url <PROD_URL>
```

Ручные проверки:

- login;
- owner dashboard;
- guest login;
- guest dashboard;
- admin dashboard;
- `/healthz`;
- `/readyz`;
- operational alerts;
- backup freshness.

## Rollback plan

Если проблема только в коде:

```bash
cd /root/cm_v2/CM_V2
git log --oneline -5
git checkout <previous_good_commit>
venv/bin/python -m compileall -q app bot scripts migrations tests
systemctl restart clubmodule.service
systemctl restart clubmodule-bot.service
```

Если проблема в миграции/данных:

1. Остановить affected services.
2. Зафиксировать ошибку и текущий commit.
3. Восстановить production DB из backup по `docs/BACKUP_RESTORE.md`.
4. Откатить код на previous good commit.
5. Запустить smoke checks.

Важно: не делать `git reset --hard` на production без понимания локальных изменений и backup состояния.

## Production readiness gate

Перед нажатием на production rollout должны быть выполнены условия:

- stage проверен вручную;
- tests проходят локально/CI;
- production backup создан;
- `migrate.py --dry-run` понятен и ожидаем;
- `.env` production проверен;
- rollback commit известен;
- есть доступ к journal/systemctl;
- есть человек, который мониторит первые 30-60 минут после релиза.


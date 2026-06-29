# Stage server runbook

This runbook is specific to the existing stage server.

## Stage target

- SSH: `root@spb-3-vm-ljpl`
- Project path: `/root/cm_stage/CM_V2`
- Git branch: `stage`
- Web service: `clubmodule-stage.service`
- Bot service: `clubmodule-stage-bot.service`

## Production boundaries

Do not touch production during stage deployment:

- Do not modify `/root/cm_v2/CM_V2`.
- Do not restart `clubmodule.service`.
- Do not restart `clubmodule-bot.service`.
- Do not restore production DB into stage unless explicitly approved.
- Do not commit `.env`, tokens, passwords, proxy URLs, or backup files.

## Read-only inspection

```bash
ssh root@spb-3-vm-ljpl
cd /root/cm_stage/CM_V2
git branch --show-current
git rev-parse --short HEAD
git status --short
git log --oneline -5
systemctl status clubmodule-stage.service --no-pager -l
systemctl status clubmodule-stage-bot.service --no-pager -l
```

## Deploy from GitHub stage branch

Use this only after the release candidate has been merged or pushed to the GitHub `stage` branch.

```bash
cd /root/cm_stage/CM_V2
git status --short
git pull --ff-only origin stage
venv/bin/python -m compileall -q app bot scripts
venv/bin/python scripts/check_environment.py --env-file .env
venv/bin/python scripts/migrate.py
systemctl restart clubmodule-stage.service
systemctl restart clubmodule-stage-bot.service
systemctl status clubmodule-stage.service --no-pager -l
systemctl status clubmodule-stage-bot.service --no-pager -l
```

## Post-deploy checks

Run these from the stage server or a machine that can reach the stage URL:

```bash
venv/bin/python scripts/smoke_http.py --base-url <STAGE_URL>
```

Also check manually:

- Owner login.
- Admin login.
- Guest Telegram login with the test bot.
- Owner dashboard.
- Guest dashboard.
- Cases/wheel.
- Missions.
- Referrals.
- CM bonuses.
- `/admin/api/system-health`.

## Refresh stage data from production

Use this only after explicitly approving a production-to-stage data refresh.
The script stops the stage bot, backs up both databases, overwrites only the
stage database with production data, runs stage migrations, restarts stage web,
and leaves the stage bot stopped.

```bash
cd /root/cm_stage/CM_V2
bash scripts/refresh_stage_from_production.sh
```

When prompted, type:

```text
REFRESH_STAGE
```

After the refresh, verify stage web and keep the stage bot stopped unless the
bot token and notification behavior are safe for testing.

## If deploy fails

1. Do not touch production.
2. Save the failing command output.
3. Check stage service logs:

```bash
journalctl -u clubmodule-stage.service -n 150 --no-pager
journalctl -u clubmodule-stage-bot.service -n 150 --no-pager
```

4. If needed, roll back only the stage checkout:

```bash
cd /root/cm_stage/CM_V2
git log --oneline -5
git checkout <previous-stage-commit>
systemctl restart clubmodule-stage.service
systemctl restart clubmodule-stage-bot.service
```

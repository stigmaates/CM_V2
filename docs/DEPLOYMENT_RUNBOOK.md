# Deployment runbook

This runbook is for managed staging and production deploys. It assumes the current live server already has a working version and must not be modified casually.

## Services

Run these as separate supervised processes:

- Web app.
- Guest Telegram bot: `run_bot.py`.
- Admin/worker Telegram bot: `run_admin_bot.py`.
- Incremental sync scripts.
- Mailing processors.
- Referral processor.

## Staging deploy

1. Create or update the staging checkout.
2. Configure staging `.env`.
3. Restore a recent production backup into the staging database if you need realistic data.
4. Install dependencies:

```bash
pip install -r requirements.txt
```

5. Apply migrations:

```bash
python3 scripts/migrate.py
```

6. Run smoke checks:

```bash
python3 -m compileall app bot scripts migrations run.py run_bot.py run_admin_bot.py
python3 -m pytest
```

7. Start the web app and check:

```bash
curl -fsS https://staging.example.com/healthz
curl -fsS https://staging.example.com/readyz
```

8. Log in as admin and check `/admin/api/system-health`.
9. Manually verify owner login, guest login, dashboard, cases/wheel, referrals, bonuses, and mailings.

## Production deploy

1. Confirm the release commit.
2. Confirm staging has passed.
3. Create a production backup:

```bash
ENV_FILE=/etc/cyber-bonus/production.env BACKUP_DIR=/var/backups/cyber-bonus scripts/backup_mysql.sh
```

4. Record the backup path.
5. Pull or check out the release commit.
6. Install dependencies.
7. Apply migrations:

```bash
ENV_FILE=/etc/cyber-bonus/production.env python3 scripts/migrate.py
```

8. Restart services one by one:
   - Web app.
   - Guest bot.
   - Admin bot.
   - Workers and scheduled jobs.

9. Check:

```bash
curl -fsS https://your-domain.example/healthz
curl -fsS https://your-domain.example/readyz
```

10. Run manual smoke checks:
    - Owner login.
    - Guest Telegram login.
    - Admin `/admin/api/system-health`.
    - Owner dashboard.
    - Guest dashboard.
    - Sync status.
    - One safe read-only CRM page.

## Rollback

Application rollback:

1. Stop the new services.
2. Check out the previous production commit.
3. Restore the previous `.env` if it changed.
4. Restart services.
5. Check `/healthz`, `/readyz`, owner login, and guest login.

Database rollback:

- Prefer a forward fix for additive migrations.
- If data is corrupted or schema is incompatible, stop services and restore the verified backup.
- Use `docs/BACKUP_RESTORE.md`.

## Release notes template

```text
Release:
Commit:
Backup:
Migration result:
Started at:
Finished at:
Smoke checks:
Issues:
Rollback needed: no/yes
```

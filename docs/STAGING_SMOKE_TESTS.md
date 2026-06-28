# Staging smoke tests

Use this after deploying to staging and after deploying to production.

## HTTP smoke check

```bash
python3 scripts/smoke_http.py --base-url https://staging.example.com
```

With expected release version:

```bash
python3 scripts/smoke_http.py --base-url https://staging.example.com --expected-version 2026.06.28-stage
```

If the database is intentionally unavailable and you only want to check the web process:

```bash
python3 scripts/smoke_http.py --base-url https://staging.example.com --skip-ready
```

## Manual checks

- Owner login.
- Guest Telegram login.
- Owner dashboard.
- Guest dashboard.
- Cases/wheel.
- Missions.
- CM bonuses.
- Referrals.
- Mailings.
- Admin `/admin/api/system-health`.

Record the result in release notes from `docs/DEPLOYMENT_RUNBOOK.md`.

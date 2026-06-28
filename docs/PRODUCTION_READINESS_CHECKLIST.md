# Production readiness checklist

Use this checklist before connecting a paid club.

## Environment

- `APP_ENV=production` is set on the server.
- `SECRET_KEY` is unique, long, and not reused between environments.
- Database credentials are not stored in git.
- Telegram bot tokens are not stored in git.
- LANGAME credentials are stored per club and are not exposed in logs.
- Server clock and timezone are configured intentionally.

## Processes

- Web app runs under a production WSGI server.
- Guest Telegram bot runs as a separate supervised process.
- Admin/worker Telegram bot runs as a separate supervised process.
- Incremental guest sync is scheduled and monitored.
- Incremental session sync is scheduled and monitored.
- Incremental operation sync is scheduled and monitored.
- Mailing processor is scheduled and monitored.
- Auto-mailing processor is scheduled and monitored.

## Data

- MySQL backups run automatically.
- Restore procedure is documented and tested.
- Database schema changes are applied through migrations.
- `python3 scripts/migrate.py` has been executed successfully before deploy.
- Runtime schema guards are reviewed and scheduled for removal after migration coverage is complete.

## Security

- Owner and admin routes are reviewed for club isolation.
- Guest routes are reviewed for guest and club isolation.
- Login endpoints have rate limiting.
- Telegram login tokens have expiration and replay protection.
- Sensitive owner/admin actions are written to an audit log.
- Production cookies use `Secure`, `HttpOnly`, and appropriate `SameSite`.

## Monitoring

- Failed syncs trigger an alert.
- Stale sync data triggers an alert.
- Bot process failures trigger an alert.
- Application errors are collected centrally.
- Mailing failures are visible to support.
- Per-club health can be checked without SSH access.

## Onboarding

- Club setup checklist is completed.
- LANGAME API connection is validated.
- Telegram guest bot flow is validated.
- Admin notification chat is validated.
- First data sync is completed and checked.
- Owner has received a short usage guide.

## Commercial

- Customer has accepted terms and privacy policy.
- Support channel and response expectations are defined.
- Tariff and included limits are documented.
- Pilot success metrics are agreed before launch.

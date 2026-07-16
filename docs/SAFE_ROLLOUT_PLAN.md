# Safe rollout plan

This project already has a live production installation. Treat the current server version as stable production and do not modify it directly.

## Hard rules

- Do not deploy this branch directly to the live server.
- Do not run migrations against the production database before a verified backup exists.
- Do not change production environment variables during development.
- Do not replace the running app, bots, cron jobs, or workers without a rollback plan.
- Do not remove runtime compatibility guards until the migration path has been tested on a production database copy.

## Recommended workflow

1. Develop in a separate branch.
2. Prepare a release candidate.
3. Clone the production database into a staging database.
4. Run migrations on staging.
5. Start the web app, guest bot, admin bot, and scheduled scripts against staging only.
6. Run smoke tests for owner, guest, Telegram login, wheel, bonuses, mailings, and sync status.
7. Review logs and compare key dashboard numbers with production.
8. Create a production database backup.
9. Deploy during a low-traffic maintenance window.
10. Run migrations on production.
11. Restart services one by one.
12. Run post-deploy smoke tests.
13. Keep rollback steps ready until the first full sync cycle completes.

Use `docs/BACKUP_RESTORE.md` and `docs/DEPLOYMENT_RUNBOOK.md` for the concrete commands.

## Staging requirements

- Separate database name.
- Separate `.env` file.
- `APP_ENV=production` can be tested only if secrets and cookies are configured correctly.
- Telegram bot tokens should be test tokens where possible.
- LANGAME sync should be limited or explicitly approved before running on staging.

## Pre-deploy checklist

- Latest production code commit is known.
- Release branch is known.
- Database backup path is known.
- Restore command has been tested recently.
- Migration command has completed on staging.
- Critical smoke tests have passed on staging.
- Expected downtime or risk window is communicated.

## Rollback plan

Application rollback:

1. Stop new version services.
2. Check out the previous production commit.
3. Restore the previous environment file if it changed.
4. Restart web app, guest bot, admin bot, and workers.
5. Verify owner login, guest login, and sync status.

Database rollback:

- Prefer forward-only fixes when possible.
- If data corruption or incompatible schema change occurs, stop services and restore the verified backup.
- Never attempt manual live schema surgery without a backup and a written command log.

## Current compatibility note

The first migration adds schema that runtime code could previously create lazily. Existing runtime `ensure_*` guards are intentionally left in place for now. This keeps the new branch safer for the first rollout because old and new code can tolerate partially upgraded environments.

After the migration has been applied successfully on all environments, remove schema-mutating runtime guards in small follow-up changes.

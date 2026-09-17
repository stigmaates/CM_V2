# Release candidate checklist

Use this checklist before pushing or deploying a production release candidate.
For the stage-to-production program, also follow
`docs/STAGE_TO_PRODUCTION_ROLLOUT.md`.

## Local checks

- Working tree is clean.
- Branch is based on the current production release branch.
- `python3 scripts/check_release_tree.py` passes.
- Production migration anchors `0030`, `0033` and `0046` are present.
- The batch contains no production unit with stage paths or stage secrets.
- Python compile check passes:

```bash
python3 -m compileall app bot scripts migrations tests run.py run_bot.py run_admin_bot.py
```

- Tests pass:

```bash
python3 -m pytest
```

- Environment preflight passes for the target environment file:

```bash
python3 scripts/check_environment.py --env-file .env
```

## Staging checks

- Staging database is separate from production.
- Production backup has been restored into staging if realistic data is needed.
- `python3 scripts/migrate.py` completes on staging.
- `/healthz` returns `ok: true`.
- `/readyz` returns `ok: true`.
- `/admin/api/system-health` has no pending migrations.
- `python3 scripts/smoke_http.py --base-url ...` passes.

## Manual product checks

- Owner login works.
- Admin login works.
- Guest Telegram login works.
- Owner dashboard opens.
- Guest dashboard opens.
- Cases/wheel tab opens.
- Mission create/update/delete works on staging data.
- Case create/update/delete works on staging data.
- Referral settings open and save.
- CM bonus redeem flow is checked with a safe test guest.
- Mailing segment preview works.

## Stop conditions

Do not deploy to production if any of these happen:

- Migration fails on staging.
- Staging `/readyz` fails.
- Admin health shows pending migrations after migration run.
- Owner or guest login fails.
- Dashboard numbers look obviously wrong compared with production.
- Backup restore has not been tested.

## Production release notes

```text
Release:
Commit:
APP_VERSION:
GIT_COMMIT:
Backup file:
Migration result:
Smoke HTTP result:
Manual checks:
Issues:
Rollback needed: no/yes
```

# Stage to production release manifest

This document is the source of truth for moving verified stage functionality
to production. It describes code and schema transfer only. Stage data,
secrets, uploads and runtime configuration never move to production.

## Baseline

Inventory captured on 2026-09-17:

- production branch: `origin/production-release-20260714` at `3986e93`;
- stage branch: `origin/product-readiness-from-stage` at `d8a6dc8`;
- integration branch: `release/stage-production-merge`, created from production;
- common ancestor: `71e43b5`;
- tip-to-tip difference: 209 files, about 22,000 added lines and 293 removed lines.

The integration branch must remain based on production. Do not merge the
stage branch wholesale: both branches contain independently cherry-picked
changes, production-only migration history and environment-specific services.

## Already present in production

Do not re-port these changes:

- international phone support;
- reusable mission templates (`0033_reusable_mission_templates`);
- Langame session guest-ID matching and orphan-session preservation;
- current club name in page titles;
- per-auto-mailing send windows (`0046_auto_mailing_send_windows`).

Patch-equivalent commits can have different hashes. Compare final files and
tests, not commit hashes alone.

## Production history that must survive

The release must retain these migration modules and their exact revision IDs:

- `0030_module_registration_capture`;
- `0033_reusable_mission_templates`;
- `0046_auto_mailing_send_windows`.

Stage migration `0029_team` also creates `module_registrations` with
`CREATE TABLE IF NOT EXISTS` and adds its trigger. It must be rehearsed on a
production database copy where `0030_module_registration_capture` is already
recorded as applied.

Two stage migrations start with `0031_`. This is supported because the runner
stores the full revision string, but both revisions must appear separately in
the dry-run output and in `schema_migrations`.

Run the repository-only guard after every integration batch:

```bash
python3 scripts/check_release_tree.py
```

The database dry run remains authoritative for a target environment:

```bash
venv/bin/python scripts/migrate.py --dry-run
```

## Forbidden production runtime artifacts

Never install or enable these on production:

- `clubmodule-stage-data-mirror.service`;
- `clubmodule-stage-data-mirror.timer`;
- `.stage-no-outbound`;
- `DISABLE_OUTBOUND_MESSAGES=1`;
- `ALLOW_STAGE_GUEST_BOT=1`;
- `ALLOW_STAGE_ADMIN_BOT=1`;
- any unit containing `/root/cm_stage/CM_V2`;
- stage database credentials, bot tokens, uploads, backups or Steam tokens.

Stage mirror source files may remain in the repository only if production
deployment instructions and service installation explicitly exclude them.

## Integration batches

Each batch is a separate reviewable commit series and production release. A
batch advances only after migration rehearsal, automated checks, smoke tests
and a monitored production cycle.

| Batch | Product scope | Schema | Runtime dependencies | Initial state |
| --- | --- | --- | --- | --- |
| 0 | Release foundation and migration compatibility | Existing production anchors | None | Internal only |
| 1 | Training video library and playlist modal | `0042_training_videos` | YouTube embeds | Admin/owner visible after smoke |
| 2 | Private admin file drive | `0043_admin_drive` | Private persistent storage, backup, Nginx request limits | Admin only |
| 3 | Team analytics, monthly reports, support tickets | `0029`, both `0031`, `0032`, `0034`, `0035` | Admin bot, PDF storage, report worker | Enable modules separately |
| 4 | Guest Pulse and CRM P/C/V | `0028_guest_pulse` | MySQL triggers, pulse worker/timer | Pilot club first |
| 5 | Steam profile and Dota history | `0036_guest_steam_accounts` | Steam Web API, OpenDota, `cryptography` | Pilot club first |
| 6 | CS2 match history | `0037_guest_cs2_matches` | Node.js CS2 GC bridge, technical Steam account | Service disabled until healthy |
| 7 | Contracts and contract refresh rewards | `0038`-`0041`, `0045` | Contract worker/timer, game match data | Off for every club |
| 8 | Game preferences and contract CRM filters | `0044_game_preferences_and_contract_engagement` | Steam and contracts | Enable after source data exists |
| 9 | Remaining UI polish | None expected | Existing web assets | After functional stabilization |

Navigation refactoring is a later release. Do not combine route/menu
reorganization with the stage-to-production transfer.

## Migration inventory expected from stage

The candidate migration list is:

- `0028_guest_pulse`;
- `0029_team`;
- `0031_support_tickets`;
- `0031_team_admin_settings`;
- `0032_support_ticket_message_tracking`;
- `0034_monthly_reports`;
- `0035_monthly_report_async`;
- `0036_guest_steam_accounts`;
- `0037_guest_cs2_matches`;
- `0038_game_contracts`;
- `0039_game_contract_rewards`;
- `0040_backfill_active_contract_rewards`;
- `0041_contract_refreshes`;
- `0042_training_videos`;
- `0043_admin_drive`;
- `0044_game_preferences_and_contract_engagement`;
- `0045_game_contract_feature_toggle`.

`0046_auto_mailing_send_windows` is already in production and must not be
reapplied. The expected production dry run must be written into each release
note before the migration is executed.

## Infrastructure inventory

### Python

Stage adds:

- `reportlab>=4.2,<5` for monthly PDFs;
- `cryptography>=43,<47` for protected CS2 credentials.

Install into the production virtual environment before restarting code that
imports them.

### Persistent storage

Configure and back up these production paths separately:

- public owner uploads (`CLUBMODULE_UPLOAD_ROOT`);
- private admin drive (`ADMIN_FILES_ROOT`), outside the public upload root;
- generated monthly reports (`MONTHLY_REPORT_ROOT`).

The web service user needs only the required permissions. Nginx must not
publish `ADMIN_FILES_ROOT`. Request body limits must cover the configured
admin file maximum without exposing private files directly.

### Guest Pulse

Create production versions of the pulse service and timer. Do not copy stage
unit files verbatim. Migration `0028_guest_pulse` creates multiple triggers,
so the production database user needs `CREATE TRIGGER` and the rehearsal must
measure ALTER/trigger installation time on a current database copy.

### Steam and Dota

Production requires its own:

- `STEAM_API_KEY`;
- `STEAM_PUBLIC_BASE_URL` using the production origin.

OpenDota uses its public API and does not require a paid key. Keep the existing
cache and request throttling.

### CS2 bridge

Before production:

- provide a production unit with `/root/cm_v2/CM_V2` paths;
- commit a dependency lock and install with `npm ci --omit=dev`;
- review dependency audit findings instead of applying a forced upgrade;
- issue a new `CS2_GC_BRIDGE_SECRET`;
- issue a new refresh token for a dedicated production technical Steam account;
- bind the bridge to `127.0.0.1` only;
- require `/health` to report `ok=true`, `steam=true`, `gc=true` before enabling consumers.

Never reuse a stage refresh token in production.

### Contracts

Create production versions of the contract service and 15-minute timer. The
club feature toggle remains off until rewards are configured and a pilot guest
has completed a reward end to end.

### Monthly reports

Stage currently starts PDF generation as a detached subprocess from the web
request. Before production, make generation a supervised worker/job or prove
that the current process survives web restarts and exposes durable failure
status and logs.

## Rehearsal on a production database copy

For every batch:

1. Restore a fresh production backup into an isolated database.
2. Record the existing `schema_migrations` rows.
3. Run `scripts/check_release_tree.py`.
4. Run `scripts/migrate.py --dry-run` and save the exact pending list.
5. Apply the migrations and record duration and lock impact.
6. Run the migration dry run again; it must report no pending revisions.
7. Run compile, unit and smoke checks.
8. Compare club, guest, session, Telegram-link, balance and reward counts.
9. Run the batch-specific rebuild/check command.
10. Restore the backup once as a rollback drill before production approval.

## Production gate for every batch

Stop if any item is missing:

- clean release worktree and reviewed diff;
- known release commit and previous-good commit;
- successful rehearsal on a current production copy;
- verified production backup and restore command;
- documented pending migration list;
- environment preflight passes;
- all new services installed but disabled before migration;
- health and readiness checks pass;
- one pilot club or admin-only rollout is available;
- logs and database load can be observed for a full worker cycle.

## Rollback

Prefer disabling the feature and stopping its new workers before reverting
application code. The migrations are intended to be additive, so unused
tables can remain during an application rollback. Restore the database only
for corruption or incompatible schema behavior, with affected services stopped.

Record for each batch:

```text
Batch:
Release commit:
Previous-good commit:
Backup:
Expected pending migrations:
Migration duration:
Services enabled:
Pilot club:
Smoke checks:
Observed errors/load:
Rollback needed: no/yes
```

# Database migrations

The project uses a lightweight Python migration runner:

```bash
python3 scripts/migrate.py
```

Run it before deploying a new production version.

## How it works

- Applied migrations are stored in the `schema_migrations` table.
- Migration files live in `migrations/versions/`.
- Each migration exposes a `revision` string and an `upgrade(cursor)` function.
- Migrations run in revision order.
- Each migration is committed only after it completes successfully.

## Current migration

`0001_product_readiness_schema` captures schema changes that were previously created lazily by runtime code:

- Cyber Bonus tables.
- Wheel token tables.
- Prize claim table.
- PC names table.
- Auto-mailing tables.
- First visit survey table.
- Bonus giveaway tables.
- Admin sync and impersonation logs.
- Audit log table.
- New compatibility columns on existing club, mission, wheel prize, and login token tables.

## Adding a migration

1. Create a new file in `migrations/versions/`.
2. Use a sortable revision prefix, for example `0002_add_support_health_checks.py`.
3. Add `revision = "0002_add_support_health_checks"`.
4. Implement `upgrade(cursor)`.
5. Make the migration safe for existing installations by checking table, column, or index existence before altering existing objects.
6. Run:

```bash
python3 -m compileall migrations scripts/migrate.py
```

## Next cleanup step

Runtime `ensure_*` schema guards still exist as a compatibility net. After the first migration is applied on all environments, gradually remove schema-mutating `ALTER TABLE` and `CREATE TABLE` calls from request-time code and keep only data seeding or existence checks that do not modify schema.

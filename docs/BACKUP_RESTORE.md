# Backup and restore

Use these commands before every production deploy and before running migrations on a live database.

## Backup

Default command:

```bash
scripts/backup_mysql.sh
```

The script reads `.env`, validates `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME`, then creates a compressed dump in `backups/`.

To use another environment file or backup directory:

```bash
ENV_FILE=/etc/cyber-bonus/production.env BACKUP_DIR=/var/backups/cyber-bonus scripts/backup_mysql.sh
```

The command prints the created backup path. Save that path in the deploy notes.

## Restore

Restore is intentionally interactive:

```bash
ENV_FILE=/etc/cyber-bonus/staging.env scripts/restore_mysql.sh /path/to/backup.sql.gz
```

You must type `RESTORE` to continue. This protects against accidental restores into the wrong database.

## Restore drill

Before the first paid rollout, test restore on staging:

1. Create a production backup.
2. Restore it into a staging database.
3. Run migrations on staging.
4. Start the app against staging.
5. Check `/healthz` and `/readyz`.
6. Log in as owner.
7. Compare key dashboard numbers with production.

## Safety notes

- Never restore into production while services are running unless this is an explicit incident response.
- Never run restore without checking `ENV_FILE`.
- Keep at least one known-good backup outside the application directory.
- Treat database backups as sensitive personal data.

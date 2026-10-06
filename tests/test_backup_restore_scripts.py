import os
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_restore_script_requires_backup_path():
    result = subprocess.run(
        ["bash", "scripts/restore_mysql.sh"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Usage:" in result.stderr


def test_restore_script_requires_matching_database(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DB_HOST=127.0.0.1",
                "DB_PORT=3306",
                "DB_USER=club",
                "DB_PASSWORD=password",
                "DB_NAME=default_db",
            ]
        ),
        encoding="utf-8",
    )
    backup_file = tmp_path / "backup.sql"
    backup_file.write_text("SELECT 1;\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/restore_mysql.sh", "--expected-db", "test", str(backup_file)],
        cwd=ROOT,
        env={
            "ENV_FILE": str(env_file),
            "PYTHON_BIN": sys.executable,
            "PATH": os.environ["PATH"],
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "environment points to 'default_db', expected 'test'" in result.stderr


def test_stage_refresh_script_requires_stage_root(tmp_path):
    result = subprocess.run(
        ["bash", "scripts/refresh_stage_from_production.sh"],
        cwd=ROOT,
        env={
            "STAGE_ROOT": str(tmp_path / "stage"),
            "PROD_ROOT": str(tmp_path / "prod"),
            "PATH": os.environ["PATH"],
            "PYTHON_BIN": sys.executable,
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Run this script from" in result.stderr


def test_backup_script_requires_env_file(tmp_path):
    result = subprocess.run(
        ["bash", "scripts/backup_mysql.sh"],
        cwd=ROOT,
        env={"ENV_FILE": str(tmp_path / "missing.env")},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Environment file not found" in result.stderr


def test_backup_script_accepts_dotenv_with_spaces(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                'DB_HOST = "127.0.0.1"',
                "DB_PORT = 3306",
                'DB_USER = "club"',
                'DB_PASSWORD = "secret with spaces"',
                'DB_NAME = "stage_db"',
            ]
        ),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "mysqldump.args"
    mysqldump = bin_dir / "mysqldump"
    mysqldump.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > {args_file}\necho 'CREATE TABLE smoke (id int);'\n",
        encoding="utf-8",
    )
    mysqldump.chmod(0o755)
    gzip = bin_dir / "gzip"
    gzip.write_text("#!/usr/bin/env bash\ncat\n", encoding="utf-8")
    gzip.chmod(0o755)

    backup_dir = tmp_path / "backups"
    result = subprocess.run(
        ["bash", "scripts/backup_mysql.sh"],
        cwd=ROOT,
        env={
            "ENV_FILE": str(env_file),
            "BACKUP_DIR": str(backup_dir),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "PYTHON_BIN": sys.executable,
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    backup_path = Path(result.stdout.strip())
    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8").startswith("CREATE TABLE smoke")
    args = args_file.read_text(encoding="utf-8")
    assert "--no-defaults" in args
    assert "--set-gtid-purged=OFF" in args
    assert "--skip-opt" in args
    assert "--skip-lock-tables" in args
    assert "--no-tablespaces" in args
    assert "--triggers" in args
    assert "--skip-triggers" not in args


def test_private_storage_backup_contains_both_private_roots(tmp_path):
    admin_root = tmp_path / "admin-drive"
    report_root = tmp_path / "monthly-reports"
    admin_root.mkdir()
    report_root.mkdir()
    (admin_root / "reference.png").write_bytes(b"image")
    (report_root / "report.pdf").write_bytes(b"pdf")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                f"ADMIN_FILES_ROOT={admin_root}",
                f"MONTHLY_REPORT_ROOT={report_root}",
            ]
        ),
        encoding="utf-8",
    )
    backup_dir = tmp_path / "backups"

    result = subprocess.run(
        [sys.executable, "scripts/backup_private_storage.py"],
        cwd=ROOT,
        env={
            "ENV_FILE": str(env_file),
            "BACKUP_DIR": str(backup_dir),
            "PATH": os.environ["PATH"],
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    backup_path = Path(result.stdout.strip())
    assert backup_path.exists()
    assert backup_path.stat().st_mode & 0o777 == 0o600
    with tarfile.open(backup_path, "r:gz") as archive:
        names = set(archive.getnames())
    assert "admin-drive/reference.png" in names
    assert "monthly-reports/report.pdf" in names


def test_enabled_gizmo_private_backup_includes_credentials_and_certificate(tmp_path, monkeypatch, capsys):
    from scripts import backup_private_storage as backup
    from app.integrations.gizmo_runtime import PRODUCTION_STATE

    assert backup.GIZMO_PRODUCTION_STATE == PRODUCTION_STATE
    roots = {name: tmp_path / name for name in ("admin", "reports", "gizmo")}
    for path in roots.values():
        path.mkdir()
    (roots["gizmo"] / "5.json").write_text('{"api_key":"test-only"}')
    (roots["gizmo"] / "5.pem").write_text("test certificate")
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"ADMIN_FILES_ROOT={roots['admin']}\nMONTHLY_REPORT_ROOT={roots['reports']}\n"
        "APP_ENV=production\nGIZMO_ENABLED=1\n"
    )
    monkeypatch.setattr(backup, "ENV_FILE", env_file)
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(backup, "GIZMO_PRODUCTION_STATE", roots["gizmo"])
    assert backup.main() == 0
    path = Path(capsys.readouterr().out.strip())
    assert path.stat().st_mode & 0o777 == 0o600
    with tarfile.open(path) as archive:
        assert archive.extractfile("gizmo/5.json").read() == b'{"api_key":"test-only"}'
        assert "gizmo/5.pem" in archive.getnames()


def test_enabled_gizmo_backup_fails_if_secrets_directory_missing(tmp_path, monkeypatch):
    import pytest
    from scripts import backup_private_storage as backup

    monkeypatch.setattr(backup, "GIZMO_PRODUCTION_STATE", tmp_path / "missing")
    values = dict(ADMIN_FILES_ROOT=str(tmp_path), MONTHLY_REPORT_ROOT=str(tmp_path))
    assert "gizmo" not in backup.backup_sources(values)
    with pytest.raises(RuntimeError, match="does not exist"):
        backup.backup_sources(dict(values, APP_ENV="production", GIZMO_ENABLED="1"))
    with pytest.raises(RuntimeError, match="APP_ENV"):
        backup.backup_sources(dict(values, APP_ENV="stage", GIZMO_ENABLED="1"))

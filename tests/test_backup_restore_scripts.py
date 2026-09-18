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

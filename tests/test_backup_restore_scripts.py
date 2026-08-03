import os
import subprocess
import sys
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
    assert "--skip-triggers" in args

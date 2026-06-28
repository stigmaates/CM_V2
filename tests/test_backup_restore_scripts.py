import subprocess
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

import gzip

import pytest

from scripts.export_guest_lifetime_research import ensure_read_only_sql, write_csv_gz


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM guests",
        "/* audit */ SELECT COUNT(*) FROM guest_sessions",
        "SHOW TABLES",
        "WITH sample AS (SELECT 1) SELECT * FROM sample",
    ],
)
def test_read_only_queries_are_allowed(sql):
    ensure_read_only_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE guests SET fio = 'x'",
        "DELETE FROM guests",
        "SELECT * FROM guests FOR UPDATE",
        "SELECT * INTO OUTFILE '/tmp/x' FROM guests",
    ],
)
def test_mutating_queries_are_rejected(sql):
    with pytest.raises(ValueError):
        ensure_read_only_sql(sql)


def test_export_rejects_direct_identifiers(tmp_path):
    with pytest.raises(ValueError, match="phone"):
        write_csv_gz(tmp_path / "unsafe.csv.gz", ["guest_id", "phone"], [])


def test_export_writes_anonymized_csv(tmp_path):
    path = tmp_path / "safe.csv.gz"
    count = write_csv_gz(path, ["club_id", "guest_id"], [{"club_id": 1, "guest_id": 2}])
    assert count == 1
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        assert handle.read() == "club_id,guest_id\n1,2\n"

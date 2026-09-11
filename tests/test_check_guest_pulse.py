"""Exercise the deployment check with real PyMySQL parameter formatting, offline."""

from unittest.mock import MagicMock

import pymysql
import pytest

from scripts import check_guest_pulse


@pytest.mark.parametrize("trigger_count, expected_exit", [(30, 0), (29, 1)])
def test_check_formats_queries_and_validates_trigger_count(monkeypatch, capsys, trigger_count, expected_exit):
    offline_connection = pymysql.connections.Connection(defer_connect=True)
    offline_connection.server_status = 0
    formatter = offline_connection.cursor()
    results = iter([
        [{"club_id": 1, "calculated_at": "2026-09-11", "backfilled_at": "2026-09-11"}],
        [{"cnt": 3459, "invalid": 0}],
        [{"days": 31, "reconstructed": 30}],
        [{"cnt": trigger_count}],
    ])
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    queries = []

    def execute(sql, params=()):
        # The original literal percent fails here even without a MySQL server.
        queries.append(formatter.mogrify(sql, params))
        cursor.fetchall.return_value = next(results)

    cursor.execute.side_effect = execute
    monkeypatch.setattr(check_guest_pulse, "get_db_connection", lambda: conn)
    monkeypatch.setattr("sys.argv", ["check_guest_pulse.py"])

    assert check_guest_pulse.main() == expected_exit
    assert "LIKE 'guest_pulse_%'" in queries[-1]
    output = capsys.readouterr()
    assert f"Guest Pulse source triggers: {trigger_count}/30" in output.out
    assert "Guest Pulse check OK" in output.out if expected_exit == 0 else "Guest Pulse check FAILED" in output.err
    conn.close.assert_called_once()

from datetime import UTC, datetime

from app.integrations.gizmo_diagnostics import describe_links


def test_report_distinguishes_missing_and_wrong_user_without_guessing():
    rows = [
        dict(id=1, userId=10, usageSessionId=100, startTime="2026-10-05T10:00:00Z"),
        dict(id=2, userId=11, usageSessionId=200, startTime="2026-10-05T10:00:00Z"),
        dict(id=3, userId=12, usageSessionId=300, startTime="2026-10-05T10:00:00Z"),
    ]
    usage = [dict(id=100, userId=10, hostId=5), dict(id=300, userId=99, hostId=6), dict(id=3, userId=12, hostId=7)]
    report = describe_links(rows, usage, datetime(2026, 10, 5, tzinfo=UTC), datetime(2026, 10, 6, tzinfo=UTC))
    assert report["counts"]["reference_matches_user"] == 1
    assert report["counts"]["reference_not_in_list"] == 1
    assert report["counts"]["different_user"] == 1
    assert report["counts"]["same_id_matches_user_not_a_verified_relation"] == 1
    mismatch = report["examples"]["different_user"][0]
    assert mismatch["referenced_usage"]["userId"] == 99
    assert mismatch["same_id_candidate_unverified"]["userId"] == 12


def test_diagnostics_limit_examples_and_never_output_names_or_phones():
    rows = [
        dict(
            id=i,
            userId=10,
            usageSessionId=999,
            startTime="2026-10-05T10:00:00Z",
            userName="PRIVATE NAME",
            phone="PRIVATE PHONE",
        )
        for i in range(1, 11)
    ]
    report = describe_links(rows, [], datetime(2026, 10, 5, tzinfo=UTC), datetime(2026, 10, 6, tzinfo=UTC))
    assert report["counts"]["reference_not_in_list"] == 10
    assert len(report["examples"]["reference_not_in_list"]) == 5
    assert "PRIVATE" not in str(report)

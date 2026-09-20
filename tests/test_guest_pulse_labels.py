from app.routes.owner.guest_pulse import _segment_labels


def _row(status, *, health=None, value=None, engagement=None):
    return {
        "lifecycle_status": status,
        "health": {"score": health, "delta_14d": None},
        "value": {"score": value},
        "engagement": {"score": engagement},
    }


def test_lifecycle_segment_is_not_repeated_in_guest_tags():
    assert _segment_labels(_row("REACTIVATED")) == []
    assert _segment_labels(_row("NEW")) == []
    assert _segment_labels(_row("ACTIVATING")) == []
    assert _segment_labels(_row("HIGH_RISK")) == []


def test_distinct_guest_segments_are_kept():
    assert _segment_labels(_row("ACTIVE", health=90, value=90, engagement=80)) == ["Активные ценные"]

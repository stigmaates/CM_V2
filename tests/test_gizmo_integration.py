from datetime import datetime
from decimal import Decimal

import pytest

from app.integrations import gizmo_normalize as normalize
from app.integrations.gizmo import GizmoError
from app.integrations.gizmo_import import all_rows, check_target


def test_gizmo_utc_timestamps_keep_the_same_instant_with_seven_fractional_digits():
    assert normalize.utc_date("2026-10-06T12:30:00.1234567+05:00") == datetime(2026, 10, 6, 7, 30, 0, 123456)
    assert normalize.utc_date("2026-10-06T07:30:00Z") == datetime(2026, 10, 6, 7, 30)
    with pytest.raises(GizmoError, match="timezone"):
        normalize.utc_date("2026-10-06T12:30:00")


def member(**values):
    return {
        "Type": 0,
        "Model": dict(
            Id=10,
            RegistrationDate="2026-01-01T00:00:00Z",
            FirstName="Иван",
            LastName="Иванов",
            Phone="8 (900) 111-22-33",
            **values,
        ),
    }


def test_member_maps_to_shared_guest_fields_and_does_not_invent_gender():
    user = normalize.guest(member(Sex=2))
    assert user["guest_id"] == 10
    assert user["fio"] == "Иванов Иван"
    assert user["phone"] == "79001112233"
    assert user["gender"] is None
    assert normalize.guest({"Type": 1, "Model": {"Id": 2}}) is None
    assert normalize.guest(member(IsDisabled=True))["phone"] is None
    assert normalize.guest(member(IsDeleted=True))["phone"] is None


def deposit(**changes):
    return dict(
        dict(
            id=50,
            userId=10,
            branchId=1,
            type=0,
            amount="120.00",
            paymentMethodId=-1,
            isVoid=False,
            isVoided=False,
            date="2026-10-01T10:00:00Z",
        ),
        **changes,
    )


def topup(row):
    return normalize.topup(row, branch_id=1, cash_method_ids={-1, -2}, guest_ids={10})


@pytest.mark.parametrize(
    "changes",
    [
        {"type": 1},
        {"type": 2},
        {"type": 3},
        {"isVoid": True},
        {"paymentMethodId": -4},
        {"paymentMethodId": None},
        {"branchId": 2},
        {"branchId": None},
        {"userId": 11},
    ],
)
def test_non_money_other_branch_and_reversals_are_not_topups(changes):
    assert topup(deposit(**changes)) is None


def test_deposit_and_later_cancellation_use_the_same_id_and_zero_the_amount():
    first = topup(deposit())
    cancelled = topup(deposit(isVoided=True))
    assert first["amount"] == Decimal("120.00")
    assert cancelled["amount"] == 0
    assert first["topup_id"] == cancelled["topup_id"] == 50


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-3", "0", "0.001", "10000000000"])
def test_invalid_money_fails_instead_of_silently_changing_totals(amount):
    with pytest.raises(GizmoError):
        topup(deposit(amount=amount))


def test_session_retains_real_id_and_host_link_without_fabricating_an_end():
    row = dict(id=20, userId=10, hostId=5, state=1, startTime="2026-10-01T10:00:00Z", endTime=None, userIsGuest=False)
    result = normalize.session(row, host_ids={5}, guest_ids={10})
    assert result["uuid"] == "gizmo:5" and result["date_stop"] is None
    assert normalize.session(row, host_ids={6}, guest_ids={10}) is None
    with pytest.raises(GizmoError, match="missing end"):
        normalize.session(dict(row, state=2), host_ids={5}, guest_ids={10})


class Client:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.params = []

    def get(self, resource, params):
        self.params.append(dict(params))
        return next(self.pages)


def test_pagination_uses_actual_opaque_cursor_and_reads_all_pages():
    client = Client([{"data": [{"id": 1}], "nextCursor": "opaque-token"}, {"data": [{"id": 2}], "nextCursor": None}])
    assert all_rows(client, "users") == [{"id": 1}, {"id": 2}]
    assert client.params[1]["Pagination.Cursor"] == "opaque-token"


@pytest.mark.parametrize(
    "pages",
    [
        [{"data": [{"id": 1}], "nextCursor": {"id": 1}}],
        [{"data": [{"id": 1}], "nextCursor": "same"}, {"data": [{"id": 2}], "nextCursor": "same"}],
        [{"data": [{"id": 1}], "nextCursor": "next"}, {"data": [{"id": 1}], "nextCursor": None}],
    ],
)
def test_unverified_or_repeating_pages_abort_the_import(pages):
    with pytest.raises(GizmoError):
        all_rows(Client(pages), "users")


@pytest.mark.parametrize(
    "club",
    [
        None,
        {"integration_provider": "langame"},
        {"integration_provider": "gizmo", "service_enabled": 1, "integration_ready": 0},
        {"integration_provider": "gizmo", "service_enabled": 0, "integration_ready": 1},
    ],
)
def test_pilot_does_not_write_to_existing_active_or_langame_club(club):
    with pytest.raises(GizmoError):
        check_target(club)


@pytest.mark.parametrize("completed", [True, False])
def test_available_session_methods_verify_same_id_user_span_and_store_utc(completed):
    from datetime import UTC

    from app.integrations.gizmo_import import collect

    class API:
        def get(self, resource, params):
            data = {
                "branches": [{"id": 1}],
                "paymentmethods": [{"id": -1}],
                "users": [member()],
                "hosts": [{"Type": 0, "Model": {"Id": 5, "Name": "PC05", "Number": 5}}],
                "deposittransactions": [deposit()],
                "usersessions": [
                    {"id": 99, "userId": 999, "hostId": 6, "state": 2, "span": 2000},
                    {"id": 123, "userId": 10, "hostId": 5, "state": 2, "span": 3590.125},
                ],
                "sessions": [
                    {
                        "id": 123,
                        "usageSessionId": 99,
                        "span": 3590.125,
                        "userId": 10,
                        "startTime": "2026-10-01T15:00:00+05:00",
                        "endTime": "2026-10-01T16:00:00+05:00" if completed else None,
                    }
                ],
            }
            assert resource != "reports/sessionslog"
            return {"data": data[resource], "nextCursor": None}

    data = collect(
        API(),
        branch_id=1,
        start=datetime(2026, 10, 1, tzinfo=UTC),
        end=datetime(2026, 10, 2, tzinfo=UTC),
        cash_method_ids={-1},
    )
    assert data["counts"]["open_sessions_skipped"] == (0 if completed else 1)
    if not completed:
        assert data["sessions"] == []
        return
    assert data["sessions"] == [
        dict(
            id=123,
            guest_id=10,
            uuid="gizmo:5",
            date_start=datetime(2026, 10, 1, 10),
            date_stop=datetime(2026, 10, 1, 11),
        )
    ]


def test_gizmo_disabled_pilot_cannot_be_activated_and_unknown_provider_is_rejected():
    from app.integrations.providers import service_activation_error, validate_provider

    assert service_activation_error({"integration_provider": "gizmo", "integration_ready": 0})
    assert service_activation_error({"integration_provider": "langame"}) is None
    with pytest.raises(ValueError):
        validate_provider("something-else")


@pytest.mark.parametrize(
    "module",
    [
        "sync_guests_incremental",
        "sync_sessions_incremental",
        "sync_balance_topups_incremental",
        "sync_operations_incremental",
    ],
)
def test_langame_workers_never_call_external_api_for_gizmo_even_if_service_enabled(monkeypatch, module):
    import importlib

    mod = importlib.import_module("scripts." + module)
    monkeypatch.setattr(
        mod, "get_clubs", lambda *args: [dict(club_id=900001, integration_provider="gizmo", service_enabled=1)]
    )

    def fail(*args, **kwargs):
        raise AssertionError("Langame job must not run for Gizmo")

    monkeypatch.setattr(mod, "start_job_run", fail)
    assert getattr(mod, module)(900001) == [{"club_id": 900001, "skipped": "provider"}]


@pytest.mark.parametrize(
    "patch",
    [
        {"userId": 99},
        {"span": 7000},
        {"span": None},
        {"span": "NaN"},
        {"span": "Infinity"},
        {"span": -1},
        {"state": 1},
        {"state": 999},
    ],
)
def test_same_id_alone_never_authorizes_session_linkage(patch):
    from app.integrations.gizmo_import import closed_session_detail

    raw = dict(
        id=24889, userId=1417, usageSessionId=24885, span=6566.929060999993, endTime="2026-09-29T04:48:30.8564568Z"
    )
    detail = dict(id=24889, userId=1417, hostId=7, state=2, span=raw["span"])
    detail.update(patch)
    with pytest.raises(GizmoError):
        closed_session_detail(raw, {24889: detail})


def test_session_link_does_not_fall_back_to_usage_reference():
    from app.integrations.gizmo_import import closed_session_detail

    raw = dict(id=123, userId=10, usageSessionId=99, span=3600, endTime="2026-10-01T11:00:00Z")
    with pytest.raises(GizmoError, match="same-ID"):
        closed_session_detail(raw, {99: dict(id=99, userId=10, hostId=5, span=3600, state=2)})

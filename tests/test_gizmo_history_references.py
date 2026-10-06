"""History must survive deletion of a source PC or member, without fake CRM users."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.integrations.gizmo import GizmoError, GizmoHTTPError
from app.integrations.gizmo_import import collect


class HistoryAPI:
    def __init__(self):
        self.calls = []
        self.member = dict(Type=0, Model=dict(Id=10, RegistrationDate="2025-01-01T00:00:00Z", Phone="79001112233"))
        self.host = dict(Type=0, Model=dict(Id=26, Name="Old PC", Number=26, IsDeleted=True))
        self.data = {
            "branches": [dict(id=1)],
            "paymentmethods": [dict(id=-1)],
            "users": [self.member],
            "hosts": [],
            "deposittransactions": [],
            "usersessions": [dict(id=123, userId=10, hostId=26, state=2, span=3600)],
            "sessions": [
                dict(id=123, userId=10, span=3600, startTime="2026-10-01T10:00:00Z", endTime="2026-10-01T11:00:00Z")
            ],
        }
        self.details = {"hosts/26": self.host, "users/10": self.member}

    def get(self, resource, params=None):
        self.calls.append(resource)
        if "/" in resource:
            result = self.details[resource]
            if isinstance(result, Exception):
                raise result
            return deepcopy(result)
        return dict(data=deepcopy(self.data[resource]), nextCursor=None)


def run(api):
    return collect(
        api, branch_id=1, start=None, end=datetime(2026, 10, 2, tzinfo=UTC), cash_method_ids={-1}, full_history=True
    )


def test_deleted_pc_restores_personal_visits_and_is_not_an_active_pc():
    api = HistoryAPI()
    api.data["sessions"].append(dict(api.data["sessions"][0], id=124))
    api.data["usersessions"].append(dict(api.data["usersessions"][0], id=124))
    data = run(api)
    assert len(data["sessions"]) == 2
    assert all(r["uuid"] == "gizmo:26" for r in data["sessions"])
    assert data["hosts"][0]["deleted"] is True
    assert data["counts"]["active_hosts"] == 0
    assert data["counts"]["archived_hosts"] == 1
    assert api.calls.count("hosts/26") == 1


def test_deleted_member_omitted_by_list_is_recovered_without_contact_details():
    api = HistoryAPI()
    api.data["users"] = []
    api.member["Model"]["IsDeleted"] = True
    data = run(api)
    assert data["guests"][0]["guest_id"] == 10
    assert data["guests"][0]["phone"] is None
    assert len(data["sessions"]) == 1
    assert api.calls.count("users/10") == 1


@pytest.mark.parametrize("status", [401, 403, 500])
def test_reference_permission_or_server_error_does_not_silently_drop_history(status):
    api = HistoryAPI()
    api.details["hosts/26"] = GizmoHTTPError("hosts/26", status)
    with pytest.raises(GizmoError, match=f"HTTP {status}"):
        run(api)


def test_host_not_found_has_an_explicit_quality_gap_instead_of_a_fake_pc():
    api = HistoryAPI()
    api.details["hosts/26"] = GizmoHTTPError("hosts/26", 404)
    data = run(api)
    assert data["hosts"] == [] and data["sessions"] == []
    assert data["counts"]["sessions_unknown_host_skipped"] == 1
    assert data["excluded_accounts"]["missing_host_ids"] == [26]


def test_detail_of_another_pc_cannot_be_attached_to_history():
    api = HistoryAPI()
    api.host["Model"]["Id"] = 27
    with pytest.raises(GizmoError, match="unexpected identity"):
        run(api)


def test_shared_login_keeps_capacity_and_money_without_creating_a_crm_person():
    api = HistoryAPI()
    api.data["users"] = []
    api.details["users/10"] = dict(Type=1, Model=dict(Id=10, IsDeleted=False))
    payment = dict(
        id=1,
        userId=10,
        branchId=1,
        date="2026-10-01T10:00:00Z",
        type=0,
        paymentMethodId=-1,
        isVoid=False,
        isVoided=False,
        amount="120.00",
    )
    api.data["deposittransactions"] = [payment, dict(payment, id=2, isVoided=True), dict(payment, id=3, isVoid=True)]
    data = run(api)
    assert data["guests"] == []
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["guest_id"] is None
    assert data["sessions"][0]["source_guest_id"] == 10
    assert all(row["guest_id"] is None for row in data["topups"])
    assert data["nonpersonal_activity"] == dict(sessions=1, topups=2, topup_amount="120.00")
    assert data["excluded_accounts"]["shared_account_ids"] == [10]
    assert api.calls.count("users/10") == 1


def test_session_ending_after_first_read_is_imported_by_next_cycle():
    api = HistoryAPI()
    api.data["sessions"][0]["endTime"] = None
    assert run(api)["sessions"] == []
    api.data["sessions"][0]["endTime"] = "2026-10-01T11:00:00Z"
    assert [r["id"] for r in run(api)["sessions"]] == [123]

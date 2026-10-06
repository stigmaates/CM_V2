"""Map Gizmo records to existing module tables; persisted event times are naive UTC."""

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.integrations.gizmo import GizmoError


def external_id(value):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise GizmoError("Invalid external entity ID")
    result = int(value)
    if result > 2**63 - 1:
        raise GizmoError("External entity ID exceeds BIGINT")
    return result


def utc_date(value, *, optional=False):
    if value is None and optional:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise GizmoError("Invalid Gizmo timestamp") from None
    if parsed.tzinfo is None:
        raise GizmoError("Gizmo timestamp has no timezone; must verify server semantics")
    return parsed.astimezone(UTC).replace(tzinfo=None)


def payload(row, allowed):
    if not isinstance(row, dict) or row.get("Type") not in allowed or not isinstance(row.get("Model"), dict):
        raise GizmoError("Unexpected Gizmo polymorphic record")
    return row["Type"], row["Model"]


def normalize_phone(value):
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    return digits if 10 <= len(digits) <= 15 else None


def guest(row):
    kind, user = payload(row, (0, 1))
    # Shared guest accounts cannot be treated as individual CRM profiles.
    if kind == 1:
        return None
    guest_id = external_id(user.get("Id"))
    inactive = user.get("IsDeleted") is True or user.get("IsDisabled") is True
    phone = None if inactive else normalize_phone(user.get("MobilePhone")) or normalize_phone(user.get("Phone"))
    name = " ".join(str(user.get(k) or "").strip() for k in ("LastName", "FirstName")).strip()
    birth = user.get("BirthDate")
    try:
        birth_date = datetime.fromisoformat(str(birth).replace("Z", "+00:00")).date() if birth else None
    except ValueError:
        raise GizmoError("Invalid Gizmo birth date") from None
    return {
        "guest_id": guest_id,
        "phone": phone,
        "fio": (name or str(user.get("Username") or f"Гость {guest_id}"))[:255],
        "birth_date": birth_date,
        "date_insert": utc_date(user.get("RegistrationDate"), optional=True),
        # The beta specification does not define the numeric Sex enum.
        "gender": None,
    }


def host(row):
    kind, model = payload(row, (0, 1))
    host_id = external_id(model.get("Id"))
    return {
        "external_id": host_id,
        "uuid": f"gizmo:{host_id}",
        "display_name": str(model.get("Name") or f"ПК {host_id}")[:120],
        "sort_order": int(model.get("Number") or host_id),
        "kind": kind,
        "deleted": model.get("IsDeleted") is True,
    }


def session(row, *, host_ids, guest_ids):
    if row.get("userIsGuest") is True:
        return None
    guest_id, host_id = external_id(row.get("userId")), external_id(row.get("hostId"))
    if host_id not in host_ids or guest_id not in guest_ids:
        return None
    start = utc_date(row.get("startTime"))
    stop = utc_date(row.get("endTime"), optional=True)
    if stop is not None and stop <= start:
        raise GizmoError("Session end must be after its start")
    state = row.get("state")
    if state not in (1, 2, 5, 9, 17, 33):
        raise GizmoError("Unknown Gizmo session state")
    if state in (2, 17) and stop is None:
        raise GizmoError("Ended/moved session is missing end time")
    return {
        "id": external_id(row.get("id")),
        "guest_id": guest_id,
        "uuid": f"gizmo:{host_id}",
        "date_start": start,
        "date_stop": stop,
    }


def topup(row, *, branch_id, cash_method_ids, guest_ids):
    """Only actual deposits from explicitly mapped payment methods count as revenue.

    A voided previously imported deposit is updated to zero, not silently retained.
    Withdraw/Charge/Credit and reversal entries never become positive topups.
    """
    if row.get("branchId") is None or int(row["branchId"]) != int(branch_id):
        return None
    if row.get("type") != 0 or row.get("isVoid") is not False:
        return None
    if row.get("paymentMethodId") is None or int(row["paymentMethodId"]) not in cash_method_ids:
        return None
    guest_id = external_id(row.get("userId"))
    if guest_id not in guest_ids:
        return None
    if not isinstance(row.get("isVoided"), bool):
        raise GizmoError("Missing deposit cancellation state")
    try:
        amount = Decimal(str(row.get("amount")))
    except (InvalidOperation, ValueError):
        raise GizmoError("Invalid deposit amount") from None
    if not amount.is_finite() or amount <= 0 or amount > Decimal("9999999999.99"):
        raise GizmoError("Invalid deposit amount")
    if amount != amount.quantize(Decimal("0.01")):
        raise GizmoError("Deposit has unsupported monetary precision")
    if row["isVoided"]:
        amount = Decimal("0.00")
    return {
        "topup_id": external_id(row.get("id")),
        "guest_id": guest_id,
        "amount": amount,
        "topup_at": utc_date(row.get("date")),
    }

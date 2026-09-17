from datetime import datetime, time, timedelta
from typing import Any

AUTO_MAILING_SEND_START = time(10, 0)
AUTO_MAILING_SEND_END = time(22, 30)


def coerce_auto_mailing_time(value: Any, default: time) -> time:
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds()) % (24 * 60 * 60)
        hours, remainder = divmod(total_seconds, 60 * 60)
        minutes, seconds = divmod(remainder, 60)
        return time(hours, minutes, seconds)
    if value not in (None, ""):
        raw = str(value).strip()
        for pattern in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(raw, pattern).time()
            except ValueError:
                continue
    return default


def format_auto_mailing_time(value: Any, default: time) -> str:
    return coerce_auto_mailing_time(value, default).strftime("%H:%M")


def is_auto_mailing_send_time(
    local_now: datetime,
    send_start: Any = None,
    send_end: Any = None,
) -> bool:
    local_time = local_now.time().replace(tzinfo=None)
    start = coerce_auto_mailing_time(send_start, AUTO_MAILING_SEND_START)
    end = coerce_auto_mailing_time(send_end, AUTO_MAILING_SEND_END)
    if start == end:
        return False
    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end

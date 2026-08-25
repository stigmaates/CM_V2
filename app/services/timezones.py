from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_CLUB_TIMEZONE = "Europe/Moscow"

CLUB_TIMEZONE_CHOICES = (
    ("Europe/Kaliningrad", "Калининград — UTC+2"),
    ("Europe/Moscow", "Москва — UTC+3"),
    ("Europe/Samara", "Самара — UTC+4"),
    ("Asia/Yekaterinburg", "Екатеринбург / Уфа — UTC+5"),
    ("Asia/Omsk", "Омск — UTC+6"),
    ("Asia/Novosibirsk", "Новосибирск — UTC+7"),
    ("Asia/Krasnoyarsk", "Красноярск — UTC+7"),
    ("Asia/Irkutsk", "Иркутск — UTC+8"),
    ("Asia/Yakutsk", "Якутск — UTC+9"),
    ("Asia/Vladivostok", "Владивосток — UTC+10"),
    ("Asia/Magadan", "Магадан — UTC+11"),
    ("Asia/Kamchatka", "Камчатка — UTC+12"),
)

_TIMEZONE_LABELS = dict(CLUB_TIMEZONE_CHOICES)


def validate_club_timezone(value: str | None) -> str:
    timezone_name = (value or DEFAULT_CLUB_TIMEZONE).strip()
    if timezone_name not in _TIMEZONE_LABELS:
        raise ValueError("Выберите часовой пояс из списка")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Выбранный часовой пояс недоступен на сервере") from exc
    return timezone_name


def get_club_timezone_label(value: str | None) -> str:
    timezone_name = value or DEFAULT_CLUB_TIMEZONE
    return _TIMEZONE_LABELS.get(timezone_name, timezone_name)


def get_club_local_now(value: str | None) -> datetime:
    timezone_name = value or DEFAULT_CLUB_TIMEZONE
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo(DEFAULT_CLUB_TIMEZONE)
    return datetime.now(timezone).replace(tzinfo=None)


def club_local_datetime_to_utc(value: datetime | None, timezone_name: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        timezone = ZoneInfo(timezone_name or DEFAULT_CLUB_TIMEZONE)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo(DEFAULT_CLUB_TIMEZONE)
    return value.replace(tzinfo=timezone).astimezone(UTC).replace(tzinfo=None)


def utc_datetime_to_club_local(value: datetime | None, timezone_name: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        timezone = ZoneInfo(timezone_name or DEFAULT_CLUB_TIMEZONE)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo(DEFAULT_CLUB_TIMEZONE)
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.astimezone(timezone).replace(tzinfo=None)

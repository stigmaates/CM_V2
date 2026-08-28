from datetime import datetime, time

AUTO_MAILING_SEND_START = time(10, 0)
AUTO_MAILING_SEND_END = time(22, 30)


def is_auto_mailing_send_time(local_now: datetime) -> bool:
    local_time = local_now.time().replace(tzinfo=None)
    return AUTO_MAILING_SEND_START <= local_time < AUTO_MAILING_SEND_END

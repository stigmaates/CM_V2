"""Fresh service checks for guest operations outside the web session gate."""


class ClubServiceDisabled(ValueError):
    def __init__(self):
        super().__init__("Обслуживание клуба приостановлено. Обратитесь к администратору клуба.")


def require_club_service(cursor, club_id, *, lock=False):
    # Acquire before guest/wallet locks. The admin disable UPDATE uses this row
    # too: an operation either commits before disable, or observes the pause.
    cursor.execute(
        "SELECT club_id, service_enabled FROM clubs WHERE club_id = %s" + (" FOR UPDATE" if lock else ""),
        (club_id,),
    )
    club = cursor.fetchone()
    if not club or (club.get("service_enabled") is not None and not int(club["service_enabled"])):
        raise ClubServiceDisabled()
    return club

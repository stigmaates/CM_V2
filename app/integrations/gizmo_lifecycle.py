"""Gizmo lifecycle exercised on isolated stage before production acceptance."""

from datetime import UTC, datetime

from app.integrations.gizmo import GizmoError
from app.integrations.stage import require_stage_environment


class SyncPaused(GizmoError):
    """An operator changed service state; this is not an integration failure."""


def mode_for(club, credentials):
    if not club or club.get("integration_provider") != "gizmo":
        raise GizmoError("Target must be a Gizmo club")
    if not credentials.get("enabled"):
        return "paused"
    ready = bool(int(club.get("integration_ready") or 0))
    enabled = bool(int(club.get("service_enabled") or 0))
    if enabled:
        if not ready:
            raise GizmoError("Обслуживание включено до завершения проверки интеграции.")
        return "service"
    if not ready:
        return "preview"
    if credentials.get("refresh_disabled") and credentials.get("requested_at_utc"):
        return "refresh"
    return "paused"


def assert_mode(club, credentials, expected):
    if mode_for(club, credentials) != expected:
        raise SyncPaused("Обслуживание клуба изменилось. Текущая загрузка остановлена.")


def read_club(conn, club_id):
    conn.rollback()  # Read committed state, not an old repeatable-read snapshot.
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM clubs WHERE club_id=%s", (club_id,))
        club = cur.fetchone()
    conn.rollback()
    return club


def activation_error(settings, credentials, state, *, now=None):
    now = now or datetime.now(UTC)
    if not credentials.get("enabled"):
        return "Сначала возобновите обновления Gizmo и дождитесь успешной загрузки."
    if state.get("status") != "complete" or state.get("phase") != "complete":
        return "Сначала дождитесь успешной загрузки данных и аналитики Gizmo."
    try:
        stamp = datetime.fromisoformat(state["last_success_at_utc"])
        age = (now - stamp).total_seconds()
    except (KeyError, TypeError, ValueError):
        return "Не определено время успешного обновления. Повторите загрузку."
    if age < 0 or age > 3600:
        return "Данные старше часа. Нажмите «Проверить и загрузить данные», затем включите обслуживание."
    if not settings.get("source") or settings["source"] != credentials.get("connection"):
        return "Настройки подключения не совпадают с загруженной историей. Повторите проверку."
    if settings.get("session_source") != "sessions+usersessions:same-id-user-span:v1":
        return "Связи сессий ещё не проверены."
    if not credentials.get("certificate_pem") or not settings["source"].get("fingerprint"):
        return "Защищённое подключение ещё не настроено."
    for projection in ("portrait", "pulse"):
        if (state.get(projection) or {}).get("status") != "updated":
            return "Дождитесь обновления CRM-портретов и Пульса гостя."
    counts = state.get("counts") or {}
    if any(
        not isinstance(counts.get(key), int) or counts[key] < 0 for key in ("guests", "hosts", "sessions", "topups")
    ):
        return "Не подтверждена полнота последней загрузки."
    return None


def check_integrity(conn, club_id):
    checks = (
        "SELECT COUNT(*) AS n FROM guest_sessions s LEFT JOIN guests g ON g.club_id=s.club_id AND g.guest_id=s.guest_id WHERE s.club_id=%s AND s.guest_id IS NOT NULL AND g.guest_id IS NULL",
        "SELECT COUNT(*) AS n FROM guest_sessions s LEFT JOIN club_pc_names p ON p.club_id=s.club_id AND p.uuid=s.uuid WHERE s.club_id=%s AND p.uuid IS NULL",
        "SELECT COUNT(*) AS n FROM guest_sessions WHERE club_id=%s AND (date_start IS NULL OR date_stop IS NULL OR date_stop<=date_start)",
        "SELECT COUNT(*) AS n FROM guest_balance_topups t LEFT JOIN guests g ON g.club_id=t.club_id AND g.guest_id=t.guest_id WHERE t.club_id=%s AND t.guest_id IS NOT NULL AND g.guest_id IS NULL",
    )
    with conn.cursor() as cur:
        for sql in checks:
            cur.execute(sql, (club_id,))
            if int(cur.fetchone()["n"]):
                raise GizmoError(
                    "В истории найдены некорректные связи или даты. Включение отложено до проверки данных."
                )


def set_service(conn, club_id, enabled, *, directory=None):
    """Enable only after a fresh complete import. Disable can interrupt collection.

    The club row lock serializes disabling with the atomic import commit. Once
    this function returns, an in-flight import cannot commit another data batch.
    """
    from app.integrations.gizmo_sync import DIRECTORY, atomic_json, private_json, read_target, run_lock

    require_stage_environment()
    directory = directory or DIRECTORY
    if not enabled:
        try:
            conn.rollback()
            conn.begin()
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM clubs WHERE club_id=%s FOR UPDATE", (club_id,))
                club = cur.fetchone()
                if not club or club.get("integration_provider") != "gizmo":
                    raise GizmoError("Target must be a Gizmo club")
                # ready=0 previews have never been enabled. Use explicit pause
                # for those rather than pretending service=0 stops onboarding.
                if not int(club.get("integration_ready") or 0):
                    raise GizmoError("Клуб ещё проходит подключение. Используйте «Приостановить обновления».")
                cur.execute("UPDATE clubs SET service_enabled=0 WHERE club_id=%s", (club_id,))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return
    with run_lock(directory / f"sync-{club_id}.lock"):
        credentials = private_json(directory / f"sync-{club_id}.json")
        settings = read_target(conn, club_id, allow_initial=True, lifecycle=True)
        state = private_json(directory / f"status-{club_id}.json")
        error = activation_error(settings, credentials, state)
        if error:
            raise GizmoError(error)
        try:
            conn.begin()
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM clubs WHERE club_id=%s FOR UPDATE", (club_id,))
                club = cur.fetchone()
                if not club or club.get("integration_provider") != "gizmo":
                    raise GizmoError("Target must be a Gizmo club")
                check_integrity(conn, club_id)
                cur.execute("UPDATE clubs SET integration_ready=1, service_enabled=1 WHERE club_id=%s", (club_id,))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        # Make the first service cycle due immediately (including snapshots).
        # If this ancillary write fails, service remains consistent and the
        # regular cadence will pick it up; no misleading 'activation failed'.
        try:
            atomic_json(directory / f"status-{club_id}.json", dict(state, status="queued", phase="queued"))
        except OSError:
            pass

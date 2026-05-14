from datetime import datetime, timedelta

from flask import flash, jsonify, redirect, render_template, request, url_for

from app.core import admin_required, get_db_connection
from app.routes.admin import admin_bp


def ensure_admin_sync_logs_table():
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_sync_logs (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    club_id INT NOT NULL,
                    script_name VARCHAR(80) NOT NULL,
                    sync_mode VARCHAR(30) NOT NULL,
                    status VARCHAR(30) NOT NULL,
                    message TEXT NULL,
                    started_at DATETIME NOT NULL,
                    finished_at DATETIME NULL,
                    created_by INT NULL,
                    INDEX idx_admin_sync_logs_club (club_id),
                    INDEX idx_admin_sync_logs_started (started_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        db.commit()


def table_has_column(table_name: str, column_name: str) -> bool:
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = %s
                  AND COLUMN_NAME = %s
                """,
                (table_name, column_name),
            )
            row = cur.fetchone()
            return bool(row and row.get("cnt"))


def get_clubs_for_admin():
    created_expr = "c.created_at" if table_has_column("clubs", "created_at") else "NULL"
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    c.club_id,
                    c.name,
                    c.owner_id,
                    u.name AS owner_name,
                    u.login AS owner_login,
                    {created_expr} AS created_at
                FROM clubs c
                LEFT JOIN users u ON u.user_id = c.owner_id
                ORDER BY c.club_id DESC
                """
            )
            return cur.fetchall()


def get_admin_metrics():
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM clubs")
            clubs_count = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(*) AS cnt FROM users")
            users_count = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE role = 'owner'")
            owners_count = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin'")
            admins_count = cur.fetchone()["cnt"]

    return {
        "clubs_count": clubs_count,
        "users_count": users_count,
        "owners_count": owners_count,
        "admins_count": admins_count,
    }


def get_club_sync_logs(club_id: int, limit: int = 8):
    ensure_admin_sync_logs_table()
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT script_name, sync_mode, status, message, started_at, finished_at
                FROM admin_sync_logs
                WHERE club_id = %s
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (club_id, limit),
            )
            return cur.fetchall()


def create_sync_log(club_id: int, script_name: str, sync_mode: str):
    ensure_admin_sync_logs_table()
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admin_sync_logs (club_id, script_name, sync_mode, status, started_at, created_by)
                VALUES (%s, %s, %s, 'running', %s, NULL)
                """,
                (club_id, script_name, sync_mode, datetime.utcnow()),
            )
            log_id = cur.lastrowid
        db.commit()
    return log_id


def finish_sync_log(log_id: int, status: str, message: str):
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE admin_sync_logs
                SET status = %s,
                    message = %s,
                    finished_at = %s
                WHERE id = %s
                """,
                (status, message[:2000] if message else None, datetime.utcnow(), log_id),
            )
        db.commit()


def run_guests_initial(club_id: int):
    from scripts.sync_guests import sync_guests
    sync_guests(club_id)


def run_sessions_initial(club_id: int):
    from scripts.sync_sessions_initial import sync_sessions_initial
    sync_sessions_initial(club_id)


def run_operations_initial(club_id: int):
    from scripts.sync_operations_initial import sync_operations_initial

    today = datetime.now().date()
    date_from = today.replace(month=1, day=1).strftime("%d.%m.%Y")
    date_to = today.strftime("%d.%m.%Y")

    sync_operations_initial(club_id, date_from=date_from, date_to=date_to)
    return f"Период: {date_from} — {date_to}. Initial sync операций завершён."


def run_guests_incremental_for_club(club_id: int):
    from scripts import sync_guests_incremental as sgi

    club = None
    for item in sgi.get_clubs():
        if int(item["club_id"]) == int(club_id):
            club = item
            break

    if not club:
        raise Exception("Клуб не найден")

    existing_ids = sgi.get_existing_guest_ids(club_id)
    guests = sgi.fetch_guests(club["secret"], club["lg_api_key"])
    filtered = sgi.filter_new_guests(guests, existing_ids)
    sgi.save_guests(club_id, filtered)
    return f"Получено гостей: {len(guests)}. К обновлению: {len(filtered)}."


def run_sessions_incremental_for_club(club_id: int):
    from scripts import sync_sessions_incremental as ssi

    club = None
    for item in ssi.get_clubs():
        if int(item["club_id"]) == int(club_id):
            club = item
            break

    if not club:
        raise Exception("Клуб не найден")

    today = datetime.now().date()
    date_from = (today - timedelta(days=2)).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")

    page = 1
    total_saved = 0
    while True:
        data = ssi.fetch_sessions(club["secret"], club["lg_api_key"], page, date_from, date_to)
        sessions = data.get("data", [])
        total_pages = data.get("total_pages", 1)

        if not sessions:
            break

        ssi.save_sessions(club_id, sessions)
        total_saved += len(sessions)

        if page >= total_pages:
            break
        page += 1

    return f"Период: {date_from} — {date_to}. Обработано сессий: {total_saved}."


def run_operations_incremental_for_club(club_id: int):
    from scripts import sync_operations_incremental as soi

    club = None
    for item in soi.get_clubs():
        if int(item["club_id"]) == int(club_id):
            club = item
            break

    if not club:
        raise Exception("Клуб не найден")

    today = datetime.now().date()
    date_from = (today - timedelta(days=soi.LOOKBACK_DAYS)).strftime("%d.%m.%Y")
    date_to = today.strftime("%d.%m.%Y")

    operations = soi.fetch_operations(club["secret"], club["lg_api_key"], club_id, date_from, date_to)
    soi.save_operations(club_id, operations)

    return f"Период: {date_from} — {date_to}. Обработано операций: {len(operations)}."


@admin_bp.route("/")
@admin_required
def admin_index():
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    ensure_admin_sync_logs_table()
    return render_template(
        "admin/dashboard.html",
        metrics=get_admin_metrics(),
        recent_clubs=get_clubs_for_admin()[:6],
        active_page="dashboard",
    )


@admin_bp.route("/clubs")
@admin_required
def clubs_list():
    ensure_admin_sync_logs_table()
    return render_template(
        "admin/clubs.html",
        clubs=get_clubs_for_admin(),
        active_page="clubs",
    )


@admin_bp.route("/clubs/<int:club_id>/details")
@admin_required
def club_details(club_id: int):
    clubs = [club for club in get_clubs_for_admin() if int(club["club_id"]) == int(club_id)]
    if not clubs:
        return jsonify({"status": False, "message": "Клуб не найден"}), 404

    return jsonify({
        "status": True,
        "club": clubs[0],
        "logs": get_club_sync_logs(club_id),
    })


@admin_bp.route("/clubs/<int:club_id>/sync/<sync_type>", methods=["POST"])
@admin_required
def club_sync(club_id: int, sync_type: str):
    actions = {
        "guests-initial": ("guests", "initial", run_guests_initial),
        "guests-incremental": ("guests", "incremental", run_guests_incremental_for_club),
        "sessions-initial": ("sessions", "initial", run_sessions_initial),
        "sessions-incremental": ("sessions", "incremental", run_sessions_incremental_for_club),
        "operations-initial": ("operations", "initial", run_operations_initial),
        "operations-incremental": ("operations", "incremental", run_operations_incremental_for_club),
    }

    if sync_type not in actions:
        return jsonify({"status": False, "message": "Неизвестный тип синхронизации"}), 400

    script_name, sync_mode, func = actions[sync_type]
    log_id = create_sync_log(club_id, script_name, sync_mode)

    try:
        result = func(club_id)
        message = result or "Синхронизация завершена"
        finish_sync_log(log_id, "success", message)
        return jsonify({"status": True, "message": message})
    except Exception as e:
        finish_sync_log(log_id, "error", str(e))
        return jsonify({"status": False, "message": str(e)}), 500

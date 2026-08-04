from datetime import datetime, timedelta
from functools import lru_cache
from threading import Thread

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from app.core import admin_required, get_db_connection
from app.routes.admin import admin_bp
from app.services.audit import record_audit_event
from app.services.job_runs import get_latest_job_runs_by_club, get_recent_job_runs
from app.services.operational_alerts import get_operational_alerts, summarize_alerts
from app.services.service_control import get_restart_controls, restart_allowed_service
from app.services.support_health import build_admin_readiness, get_admin_system_health

SYNC_JOB_TYPES = [
    "sync_guests_incremental",
    "sync_sessions_incremental",
    "sync_operations_incremental",
    "sync_balance_topups_incremental",
]

SYNC_JOB_LABELS = {
    "sync_guests_incremental": "Гости",
    "sync_sessions_incremental": "Сессии",
    "sync_operations_incremental": "Операции",
    "sync_balance_topups_incremental": "Пополнения",
}

JOB_TYPE_LABELS = {
    **SYNC_JOB_LABELS,
    "process_mailing": "Рассылка",
    "process_auto_mailing": "Авторассылка",
    "process_referrals": "Рефералы",
}

SYNC_STALE_HOURS = {
    "sync_guests_incremental": 24,
    "sync_sessions_incremental": 8,
    "sync_operations_incremental": 8,
    "sync_balance_topups_incremental": 8,
}


def ensure_admin_sync_logs_table():
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute("""
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
                """)
        db.commit()


def ensure_admin_impersonation_logs_table():
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admin_impersonation_logs (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    admin_user_id INT NOT NULL,
                    admin_login VARCHAR(120) NULL,
                    club_id INT NOT NULL,
                    club_name VARCHAR(255) NULL,
                    started_at DATETIME NOT NULL,
                    ended_at DATETIME NULL,
                    ip VARCHAR(80) NULL,
                    user_agent TEXT NULL,
                    INDEX idx_admin_impersonation_admin (admin_user_id),
                    INDEX idx_admin_impersonation_club (club_id),
                    INDEX idx_admin_impersonation_started (started_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
        db.commit()


def get_club_by_id(club_id: int):
    service_enabled_expr = "service_enabled" if table_has_column("clubs", "service_enabled") else "1"
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                f"""
                SELECT club_id, name, {service_enabled_expr} AS service_enabled
                FROM clubs
                WHERE club_id = %s
                LIMIT 1
                """,
                (club_id,),
            )
            return cur.fetchone()


def create_impersonation_log(club_id: int, club_name: str | None):
    ensure_admin_impersonation_logs_table()
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admin_impersonation_logs (
                    admin_user_id, admin_login, club_id, club_name, started_at, ip, user_agent
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session.get("user_id"),
                    session.get("login"),
                    club_id,
                    club_name,
                    datetime.utcnow(),
                    request.headers.get("X-Forwarded-For", request.remote_addr),
                    request.headers.get("User-Agent"),
                ),
            )
            log_id = cur.lastrowid
        db.commit()
    return log_id


def finish_impersonation_log(log_id):
    if not log_id:
        return
    ensure_admin_impersonation_logs_table()
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE admin_impersonation_logs
                SET ended_at = %s
                WHERE id = %s
                  AND ended_at IS NULL
                """,
                (datetime.utcnow(), log_id),
            )
        db.commit()


@lru_cache(maxsize=64)
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
    service_enabled_expr = "c.service_enabled" if table_has_column("clubs", "service_enabled") else "1"
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(f"""
                SELECT
                    c.club_id,
                    {service_enabled_expr} AS service_enabled,
                    c.name,
                    c.owner_id,
                    u.name AS owner_name,
                    u.login AS owner_login,
                    {created_expr} AS created_at
                FROM clubs c
                LEFT JOIN users u ON u.user_id = c.owner_id
                ORDER BY c.club_id DESC
                """)
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


def _format_job_age(dt):
    if not dt:
        return "—"

    delta = datetime.utcnow() - dt
    total_minutes = max(0, int(delta.total_seconds() // 60))
    if total_minutes < 60:
        return f"{total_minutes} мин назад"

    total_hours = total_minutes // 60
    if total_hours < 48:
        return f"{total_hours} ч назад"

    return f"{total_hours // 24} дн назад"


def _job_state(job_type: str, row):
    if not row:
        return {
            "label": SYNC_JOB_LABELS[job_type],
            "status": "none",
            "status_label": "нет данных",
            "age_label": "—",
            "rows_saved": None,
            "error_text": None,
        }

    status = row.get("status") or "unknown"
    started_at = row.get("started_at")
    stale_hours = SYNC_STALE_HOURS.get(job_type, 24)
    is_stale = bool(started_at and datetime.utcnow() - started_at > timedelta(hours=stale_hours))
    view_status = "stale" if status == "success" and is_stale else status
    status_labels = {
        "success": "ok",
        "error": "ошибка",
        "running": "идёт",
        "stale": "устарело",
        "skipped_locked": "пропущено",
        "skipped_disabled": "выключено",
    }

    return {
        "label": SYNC_JOB_LABELS[job_type],
        "status": view_status,
        "status_label": status_labels.get(view_status, view_status),
        "age_label": _format_job_age(started_at),
        "rows_saved": row.get("rows_saved"),
        "error_text": row.get("error_text"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "rows_received": row.get("rows_received"),
    }


def _overall_sync_status(jobs):
    if any(job["status"] == "error" for job in jobs):
        return "error"
    if any(job["status"] in {"none", "stale"} for job in jobs):
        return "stale"
    if any(job["status"] == "running" for job in jobs):
        return "running"
    return "success"


def _is_club_service_enabled(club) -> bool:
    value = club.get("service_enabled", 1)
    if value is None:
        return True
    return bool(int(value))


def get_club_sync_health(clubs):
    latest_by_club = get_latest_job_runs_by_club(SYNC_JOB_TYPES)
    health = []

    for club in clubs:
        club_id = int(club["club_id"])
        if not _is_club_service_enabled(club):
            health.append(
                {
                    "club_id": club_id,
                    "name": club.get("name"),
                    "overall": "disabled",
                    "jobs": [],
                }
            )
            continue

        latest = latest_by_club.get(club_id, {})
        jobs = [_job_state(job_type, latest.get(job_type)) for job_type in SYNC_JOB_TYPES]
        overall = _overall_sync_status(jobs)

        health.append(
            {
                "club_id": club_id,
                "name": club.get("name"),
                "overall": overall,
                "jobs": jobs,
            }
        )

    return health


def summarize_sync_health(club_sync_health):
    summary = {"success": 0, "stale": 0, "error": 0, "running": 0, "disabled": 0}
    for club in club_sync_health:
        status = club.get("overall") or "stale"
        if status not in summary:
            summary[status] = 0
        summary[status] += 1
    summary["total"] = len(club_sync_health)
    return summary


def get_recent_job_runs_for_dashboard(limit: int = 12):
    rows = get_recent_job_runs(limit=limit)
    for row in rows:
        row["job_label"] = JOB_TYPE_LABELS.get(row.get("job_type"), row.get("job_type"))
    return rows


def get_club_sync_logs(club_id: int, limit: int = 8):
    ensure_admin_sync_logs_table()
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT id, script_name, sync_mode, status, message, started_at, finished_at
                FROM admin_sync_logs
                WHERE club_id = %s
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (club_id, limit),
            )
            return cur.fetchall()


def get_running_sync_log(club_id: int, script_name: str, sync_mode: str):
    ensure_admin_sync_logs_table()
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT id, message, started_at
                FROM admin_sync_logs
                WHERE club_id = %s
                  AND script_name = %s
                  AND sync_mode = %s
                  AND status = 'running'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (club_id, script_name, sync_mode),
            )
            return cur.fetchone()


def create_sync_log(club_id: int, script_name: str, sync_mode: str, message: str | None = None):
    ensure_admin_sync_logs_table()
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admin_sync_logs (club_id, script_name, sync_mode, status, message, started_at, created_by)
                VALUES (%s, %s, %s, 'running', %s, %s, NULL)
                """,
                (club_id, script_name, sync_mode, message, datetime.utcnow()),
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


def update_sync_log_progress(log_id: int, message: str):
    if not log_id:
        return
    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE admin_sync_logs
                SET message = %s
                WHERE id = %s
                  AND status = 'running'
                """,
                (message[:2000] if message else None, log_id),
            )
        db.commit()


def _sync_progress(log_id: int):
    return lambda message: update_sync_log_progress(log_id, message)


def run_admin_sync_job(
    *,
    club_id: int,
    script_name: str,
    sync_mode: str,
    func,
    log_id: int,
    actor_user_id: int | None = None,
    actor_role: str | None = None,
):
    try:
        if sync_mode == "initial" and script_name in {"guests", "sessions"}:
            result = func(club_id, log_id=log_id)
        else:
            result = func(club_id)
        message = result or "Синхронизация завершена"
        finish_sync_log(log_id, "success", message)
        record_audit_event(
            action="admin.club_sync.run",
            club_id=club_id,
            entity_type="admin_sync_log",
            entity_id=log_id,
            details={"script_name": script_name, "sync_mode": sync_mode, "status": "success"},
            actor_user_id=actor_user_id,
            actor_role=actor_role,
        )
    except Exception as e:
        finish_sync_log(log_id, "error", str(e))
        record_audit_event(
            action="admin.club_sync.run",
            club_id=club_id,
            entity_type="admin_sync_log",
            entity_id=log_id,
            details={"script_name": script_name, "sync_mode": sync_mode, "status": "error", "error": str(e)},
            actor_user_id=actor_user_id,
            actor_role=actor_role,
        )


def run_guests_initial(club_id: int, log_id: int | None = None):
    from scripts.sync_guests import sync_guests

    result = sync_guests(club_id, progress=_sync_progress(log_id) if log_id else None)
    return f"Получено гостей: {result.get('received', 0)}. Сохранено/обновлено: {result.get('saved', 0)}."


def run_sessions_initial(club_id: int, log_id: int | None = None):
    from scripts.sync_sessions_initial import sync_sessions_initial

    result = sync_sessions_initial(club_id, progress=_sync_progress(log_id) if log_id else None)
    return f"Сохранено сессий: {result.get('saved', 0)}. Пропущено без гостя: {result.get('skipped', 0)}."


def run_operations_initial(club_id: int):
    from scripts.sync_operations_initial import sync_operations_initial

    today = datetime.now().date()
    date_from = today.replace(month=1, day=1).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")

    sync_operations_initial(club_id, date_from=date_from, date_to=date_to)
    return f"Период: {date_from} — {date_to}. Initial sync операций завершён."


def run_balance_topups_initial(club_id: int):
    from scripts.sync_balance_topups_initial import sync_balance_topups_initial

    today = datetime.now().date()
    date_from = today.replace(month=1, day=1).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")

    result = sync_balance_topups_initial(club_id, date_from=date_from, date_to=date_to)
    return f"Период: {date_from} — {date_to}. Получено пополнений: {result.get('received', 0)}. Сохранено: {result.get('saved', 0)}."


def run_guests_incremental_for_club(club_id: int):
    from scripts.sync_guests_incremental import sync_guests_incremental

    result = sync_guests_incremental(club_id)
    item = result[0] if result else {"received": 0, "filtered": 0, "saved": 0}
    return f"Получено гостей: {item.get('received', 0)}. К обновлению: {item.get('filtered', 0)}. Сохранено: {item.get('saved', 0)}."


def run_sessions_incremental_for_club(club_id: int):
    from scripts.sync_sessions_incremental import sync_sessions_incremental

    result = sync_sessions_incremental(club_id)
    item = result[0] if result else {"saved": 0, "date_from": "", "date_to": ""}
    return f"Период: {item.get('date_from')} — {item.get('date_to')}. Обработано сессий: {item.get('saved', 0)}."


def run_operations_incremental_for_club(club_id: int):
    from scripts.sync_operations_incremental import sync_operations_incremental

    result = sync_operations_incremental(club_id)
    item = result[0] if result else {"received": 0, "saved": 0, "date_from": "", "date_to": ""}
    return f"Период: {item.get('date_from')} — {item.get('date_to')}. Получено операций: {item.get('received', 0)}. Сохранено: {item.get('saved', 0)}."


def run_balance_topups_incremental_for_club(club_id: int):
    from scripts.sync_balance_topups_incremental import sync_balance_topups_incremental

    result = sync_balance_topups_incremental(club_id)
    item = result[0] if result else {"received": 0, "saved": 0, "date_from": "", "date_to": ""}
    return f"Период: {item.get('date_from')} — {item.get('date_to')}. Получено пополнений: {item.get('received', 0)}. Сохранено: {item.get('saved', 0)}."


@admin_bp.route("/")
@admin_required
def admin_index():
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    ensure_admin_sync_logs_table()
    ensure_admin_impersonation_logs_table()
    clubs = get_clubs_for_admin()
    club_sync_health = get_club_sync_health(clubs)
    sync_health_summary = summarize_sync_health(club_sync_health)
    operational_alerts = get_operational_alerts(problem_job_limit=10)
    operational_alert_summary = summarize_alerts(operational_alerts)
    recent_job_runs = get_recent_job_runs_for_dashboard(limit=12)
    system_health = get_admin_system_health()
    readiness = build_admin_readiness(
        system_health=system_health,
        alert_summary=operational_alert_summary,
        sync_summary=sync_health_summary,
        recent_job_runs=recent_job_runs,
    )
    return render_template(
        "admin/dashboard.html",
        metrics=get_admin_metrics(),
        recent_clubs=clubs[:6],
        club_sync_health=club_sync_health,
        sync_health_summary=sync_health_summary,
        operational_alerts=operational_alerts[:8],
        operational_alert_summary=operational_alert_summary,
        recent_job_runs=recent_job_runs,
        system_health=system_health,
        readiness=readiness,
        restart_controls=get_restart_controls(),
        active_page="dashboard",
    )


@admin_bp.route("/services/<service_name>/restart", methods=["POST"])
@admin_required
def restart_service(service_name: str):
    result = restart_allowed_service(service_name)
    record_audit_event(
        action="admin.service.restart",
        entity_type="systemd_service",
        entity_id=service_name,
        details=result,
    )

    if result.get("ok"):
        flash(f"Перезапуск поставлен в очередь: {result.get('label') or service_name}", "success")
    elif result.get("error") == "service_restart_disabled":
        flash("Перезапуск сервисов выключен в конфигурации", "error")
    elif result.get("error") == "service_not_allowed":
        flash("Этот сервис не разрешён для перезапуска из админки", "error")
    else:
        flash(f"Не удалось перезапустить сервис: {result.get('error')}", "error")

    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/clubs")
@admin_required
def clubs_list():
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

    return jsonify(
        {
            "status": True,
            "club": clubs[0],
            "logs": get_club_sync_logs(club_id),
        }
    )


@admin_bp.route("/clubs/<int:club_id>/sync-logs")
@admin_required
def club_sync_logs(club_id: int):
    club = get_club_by_id(club_id)
    if not club:
        return jsonify({"status": False, "message": "Клуб не найден"}), 404

    return jsonify({"status": True, "logs": get_club_sync_logs(club_id)})


@admin_bp.route("/clubs/<int:club_id>/service", methods=["POST"])
@admin_required
def club_service_toggle(club_id: int):
    payload = request.get_json(silent=True) or {}
    enabled = bool(payload.get("enabled")) if request.is_json else request.form.get("enabled") == "1"
    club = get_club_by_id(club_id)
    if not club:
        return jsonify({"status": False, "message": "Клуб не найден"}), 404

    with get_db_connection() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE clubs
                SET service_enabled = %s
                WHERE club_id = %s
                """,
                (1 if enabled else 0, club_id),
            )
        db.commit()

    record_audit_event(
        action="admin.club_service.toggle",
        club_id=club_id,
        entity_type="club",
        entity_id=club_id,
        details={"service_enabled": enabled},
    )

    return jsonify(
        {
            "status": True,
            "message": "Обслуживание включено" if enabled else "Обслуживание выключено",
            "service_enabled": enabled,
        }
    )


@admin_bp.route("/api/system-health")
@admin_required
def api_system_health():
    return jsonify(get_admin_system_health())


@admin_bp.route("/api/operational-alerts")
@admin_required
def api_operational_alerts():
    alerts = get_operational_alerts(problem_job_limit=20)
    return jsonify(
        {
            "ok": not any(alert.get("severity") == "error" for alert in alerts),
            "summary": summarize_alerts(alerts),
            "alerts": alerts,
        }
    )


@admin_bp.route("/api/clubs/<int:club_id>/health")
@admin_required
def api_club_health(club_id: int):
    club = get_club_by_id(club_id)
    if not club:
        return jsonify({"ok": False, "message": "Клуб не найден"}), 404

    health = get_club_sync_health([club])[0]
    return jsonify(
        {
            "ok": health["overall"] == "success",
            "club": {
                "club_id": int(club["club_id"]),
                "name": club.get("name"),
            },
            "sync": {
                "overall": health["overall"],
                "jobs": health["jobs"],
            },
        }
    )


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
        "balance-topups-initial": ("balance_topups", "initial", run_balance_topups_initial),
        "balance-topups-incremental": ("balance_topups", "incremental", run_balance_topups_incremental_for_club),
    }

    if sync_type not in actions:
        return jsonify({"status": False, "message": "Неизвестный тип синхронизации"}), 400

    club = get_club_by_id(club_id)
    if not club:
        return jsonify({"status": False, "message": "Клуб не найден"}), 404
    if not _is_club_service_enabled(club):
        return jsonify({"status": False, "message": "Клуб выключен, синхронизация недоступна"}), 400

    script_name, sync_mode, func = actions[sync_type]
    running_log = get_running_sync_log(club_id, script_name, sync_mode)
    if running_log:
        message = (
            "Такая синхронизация уже выполняется. "
            "Прогресс обновляется в логах ниже."
        )
        return jsonify(
            {
                "status": True,
                "queued": True,
                "already_running": True,
                "log_id": running_log["id"],
                "message": message,
            }
        )

    log_id = create_sync_log(
        club_id,
        script_name,
        sync_mode,
        message="Синхронизация поставлена в очередь",
    )
    worker = Thread(
        target=run_admin_sync_job,
        kwargs={
            "club_id": club_id,
            "script_name": script_name,
            "sync_mode": sync_mode,
            "func": func,
            "log_id": log_id,
            "actor_user_id": session.get("user_id"),
            "actor_role": session.get("role"),
        },
        daemon=True,
    )
    worker.start()

    message = (
        "Синхронизация запущена в фоне. "
        "Прогресс обновляется в логах ниже."
    )
    return jsonify(
        {
            "status": True,
            "queued": True,
            "log_id": log_id,
            "message": message,
        }
    )


@admin_bp.route("/clubs/<int:club_id>/impersonate", methods=["POST"])
@admin_required
def start_owner_impersonation(club_id: int):
    club = get_club_by_id(club_id)
    if not club:
        flash("Клуб не найден", "error")
        return redirect(url_for("admin.clubs_list"))

    # Finish previous unfinished impersonation session for this browser session, if any.
    finish_impersonation_log(session.get("impersonation_log_id"))

    if "original_club_id" not in session:
        session["original_club_id"] = session.get("club_id")
    if "original_club_name" not in session:
        session["original_club_name"] = session.get("club_name")

    log_id = create_impersonation_log(int(club["club_id"]), club.get("name"))
    record_audit_event(
        action="admin.impersonation.start",
        club_id=int(club["club_id"]),
        entity_type="admin_impersonation_log",
        entity_id=log_id,
        details={"club_name": club.get("name")},
    )

    session["impersonating_owner"] = True
    session["impersonated_club_id"] = int(club["club_id"])
    session["impersonated_club_name"] = club.get("name")
    session["impersonation_log_id"] = log_id
    session["club_id"] = int(club["club_id"])
    session["club_name"] = club.get("name")

    flash(f"Открыт режим владельца для клуба «{club.get('name') or club_id}»", "success")
    return redirect(url_for("owner.dashboard"))


@admin_bp.route("/impersonation/stop")
@admin_required
def stop_owner_impersonation():
    impersonated_club_id = session.get("impersonated_club_id")
    impersonation_log_id = session.get("impersonation_log_id")
    finish_impersonation_log(session.get("impersonation_log_id"))
    record_audit_event(
        action="admin.impersonation.stop",
        club_id=int(impersonated_club_id) if impersonated_club_id else None,
        entity_type="admin_impersonation_log",
        entity_id=impersonation_log_id,
    )

    original_club_id = session.pop("original_club_id", None)
    original_club_name = session.pop("original_club_name", None)

    for key in (
        "impersonating_owner",
        "impersonated_club_id",
        "impersonated_club_name",
        "impersonation_log_id",
    ):
        session.pop(key, None)

    session["club_id"] = original_club_id
    session["club_name"] = original_club_name

    flash("Режим просмотра клуба как владелец завершён", "success")
    return redirect(url_for("admin.clubs_list"))

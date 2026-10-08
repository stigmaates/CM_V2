"""External watchdog: no dependency on the guest event loop or database health."""

from app.services.bot_health import diagnose, recovery_allowed


def run_check(state, heartbeat, service, *, now, monotonic, boot, notify, restart, persist):
    """Persist recovery budget before acting, and retain incidents until recovery is announced."""
    state = dict(state)
    if service["active"] in ("inactive", "deactivating"):
        # Respect deliberate maintenance stops; systemd owns ordinary crash restarts.
        return dict(state, status="paused", checked_at=now)
    if service["active"] == "activating":
        return dict(state, status="starting", checked_at=now)
    problem = (
        "bot_process_failed"
        if service["active"] == "failed"
        else diagnose(heartbeat, pid=service["pid"], uptime=service["uptime"], now=monotonic, boot=boot)
    )
    if not problem and service["uptime"] < 180:
        return dict(state, status="starting", checked_at=now)
    if not problem:
        if state.get("incident"):
            if notify(
                "bot_recovered", "Вход через Telegram снова доступен. Получение сообщений и обработчик отвечают."
            ):
                state.pop("incident", None)
                state.pop("last_alert_at", None)
                state.pop("last_alert_code", None)
        return dict(state, status="healthy", checked_at=now)
    state.setdefault("incident", dict(started_at=now))
    allowed, recent = recovery_allowed(state.get("restarts", []), now=now)
    # First announce the outage. Notify failures must not prevent recovery.
    code = problem if allowed else "bot_recovery_limited"
    if state.get("last_alert_code") != code or now - state.get("last_alert_at", 0) >= 3600:
        action = (
            "Запускаем автоматическое восстановление."
            if allowed
            else "Повторный перезапуск сейчас запрещён защитой от частых рестартов. Требуется проверка администратора."
        )
        if notify(code, action):
            state.update(last_alert_at=now, last_alert_code=code)
    state.update(status="unhealthy", problem=problem, checked_at=now, restarts=recent)
    if allowed:
        state["restarts"] = recent + [now]
        state["status"] = "restart_requested"
        persist(state)  # A killed checker cannot repeat an unrecorded restart.
        try:
            restart()
        except Exception as exc:
            state.update(status="restart_failed", restart_error=type(exc).__name__)
    return state

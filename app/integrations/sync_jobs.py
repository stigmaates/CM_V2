"""One provider-aware registry for synchronization health and monitoring."""

from app.integrations.providers import provider_for

LANGAME_SYNC_JOBS = (
    "sync_guests_incremental",
    "sync_sessions_incremental",
    "sync_operations_incremental",
    "sync_balance_topups_incremental",
)
GIZMO_SYNC_JOB = "sync_gizmo"
SYNC_JOB_TYPES = [*LANGAME_SYNC_JOBS, GIZMO_SYNC_JOB]
SYNC_JOB_LABELS = {
    "sync_guests_incremental": "Гости",
    "sync_sessions_incremental": "Сессии",
    "sync_operations_incremental": "Операции",
    "sync_balance_topups_incremental": "Пополнения",
    GIZMO_SYNC_JOB: "Gizmo: гости, ПК, сессии, пополнения и аналитика",
}
SYNC_STALE_HOURS = {
    "sync_guests_incremental": 24,
    "sync_sessions_incremental": 8,
    "sync_operations_incremental": 8,
    "sync_balance_topups_incremental": 8,
    GIZMO_SYNC_JOB: 2,
}


def sync_jobs_for(club):
    return (GIZMO_SYNC_JOB,) if provider_for(club) == "gizmo" else LANGAME_SYNC_JOBS

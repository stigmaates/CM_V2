"""The provider is part of club identity, not a switch for relabelling existing data."""

PROVIDERS = {"langame": "Langame", "gizmo": "Gizmo"}


def validate_provider(value):
    value = (value or "langame").strip().lower()
    if value not in PROVIDERS:
        raise ValueError("Неизвестная система клуба")
    return value


def provider_for(club):
    return validate_provider(club.get("integration_provider"))


def supports_langame_sync(club):
    return provider_for(club) == "langame"


def service_activation_error(club):
    if provider_for(club) == "gizmo" and not int(club.get("integration_ready") or 0):
        return "Gizmo: сначала завершите проверку импорта на стейдже. Обслуживание пока недоступно."
    return None

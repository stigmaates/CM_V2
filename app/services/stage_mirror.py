"""Identify the checkout managed by the stage data-mirror installer."""

from pathlib import Path

MIRROR_MARKER = Path(__file__).resolve().parents[2] / '.stage-no-outbound'


def stage_mirror_enabled() -> bool:
    # This local installer marker is not copied from the production database.
    # Disabling messages through an environment variable alone is not mirror mode.
    return MIRROR_MARKER.is_file()

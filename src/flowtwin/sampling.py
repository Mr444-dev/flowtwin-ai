from __future__ import annotations

from .config import SNAPSHOT_PREFIX_COUNTS


def snapshot_prefix_counts(event_count: int) -> tuple[int, ...]:
    """Choose observable event-count checkpoints without consulting trace length."""
    if event_count < 2:
        return ()
    return tuple(prefix for prefix in SNAPSHOT_PREFIX_COUNTS if prefix < event_count)


def stage_for_prefix(prefix_count: int) -> str:
    """Assign a reporting stage using only the number of events already seen."""
    if prefix_count < 1:
        raise ValueError("prefix_count must be positive.")
    if prefix_count <= 3:
        return "early"
    if prefix_count <= 10:
        return "mid"
    return "late"

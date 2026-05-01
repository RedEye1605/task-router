"""Priority scoring engine for Task Router."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from task_router.db import list_tasks, update_task, get_connection

log = logging.getLogger(__name__)

# Scoring weights
W_DEADLINE = 0.5
W_SOURCE = 0.3
W_EFFORT = 0.2

# Source weights: higher = more authoritative / time-sensitive
SOURCE_WEIGHTS: dict[str, float] = {
    "calendar": 0.9,
    "email": 0.8,
    "notion": 0.7,
    "whatsapp": 0.6,
    "inbox": 0.5,
    "manual": 0.4,
}

# Effort inverse: quick tasks get higher score (do first)
EFFORT_INVERSE: dict[str, float] = {
    "quick": 0.9,
    "medium": 0.5,
    "heavy": 0.3,
}


def deadline_urgency(due: str | None) -> float:
    """Calculate urgency based on deadline proximity."""
    if not due:
        return 0.1

    try:
        # Parse ISO-8601 date (handle both date-only and datetime)
        due_str = due.strip()
        if "T" in due_str:
            due_dt = datetime.fromisoformat(due_str)
        else:
            due_dt = datetime.strptime(due_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )

        # Ensure timezone-aware
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        delta = due_dt - now

        if delta.total_seconds() < 0:
            return 1.0  # Overdue
        elif delta < timedelta(hours=24):
            return 0.8
        elif delta < timedelta(days=3):
            return 0.5
        elif delta < timedelta(days=7):
            return 0.2
        else:
            return 0.1
    except (ValueError, TypeError):
        log.warning("Could not parse due date: %s", due)
        return 0.1


def compute_score(
    due: str | None,
    source: str,
    effort: str,
) -> float:
    """Compute priority score for a task."""
    d_urgency = deadline_urgency(due)
    s_weight = SOURCE_WEIGHTS.get(source, 0.4)
    e_inverse = EFFORT_INVERSE.get(effort, 0.5)

    return W_DEADLINE * d_urgency + W_SOURCE * s_weight + W_EFFORT * e_inverse


def rescore_all(db_path: Any = None) -> int:
    """Recalculate scores for all open/in_progress tasks. Returns count updated."""
    tasks = list_tasks(db_path=db_path)
    count = 0
    for task in tasks:
        if task["status"] in ("done", "blocked"):
            continue
        score = compute_score(task["due"], task["source"], task["effort"])
        update_task(task["id"], db_path=db_path, score=score)
        count += 1
    log.info("Rescored %d tasks", count)
    return count

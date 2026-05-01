"""Calendar ingestion — shell out to existing gcal.py."""

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from task_router.db import add_task, get_sync_state, set_sync_state, find_by_source_ref
from task_router.scorer import compute_score

log = logging.getLogger(__name__)

GCAL_SCRIPT = Path.home() / ".openclaw/scripts/google/gcal.py"
GCAL_PYTHON = Path.home() / ".openclaw/scripts/google/venv/bin/python"


def ingest_calendar(days: int = 14, db_path: Path | None = None) -> int:
    """Ingest upcoming calendar events. Returns count of new tasks created."""
    if not GCAL_SCRIPT.exists():
        log.warning("gcal.py not found at %s — skipping calendar ingest", GCAL_SCRIPT)
        return 0

    try:
        result = subprocess.run(
            [str(GCAL_PYTHON), str(GCAL_SCRIPT), "list", "--days", str(days)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.warning("Calendar ingestion failed: %s", exc)
        return 0

    if result.returncode != 0:
        log.warning("gcal.py returned %d: %s", result.returncode, result.stderr[:200])
        return 0

    events = _parse_gcal_output(result.stdout)
    count = 0
    now = datetime.now(timezone.utc).isoformat()

    for event in events:
        ref = f"calendar:{event.get('id', event['title'])}"
        existing = find_by_source_ref(ref, db_path=db_path)
        if existing and existing["status"] != "done":
            continue  # Already tracked

        due = event.get("start", "")
        score = compute_score(due, "calendar", "quick")
        add_task(
            title=event["title"],
            source="calendar",
            description=event.get("description", ""),
            due=due,
            priority="high",
            effort="quick",
            source_ref=ref,
            tags=["calendar"],
            score=score,
            db_path=db_path,
        )
        count += 1

    set_sync_state("calendar", now, db_path=db_path)
    log.info("Calendar ingestion: %d new tasks", count)
    return count


def _parse_gcal_output(output: str) -> list[dict]:
    """Parse gcal.py list output into event dicts.

    Expected output format (one event per section):
      Title: <title>
      Start: <datetime>
      End: <datetime>
      ---
    Or JSON array if gcal.py supports --json.
    """
    events = []
    output = output.strip()
    if not output:
        return events

    # Try JSON first
    try:
        items = json.loads(output)
        if isinstance(items, list):
            return items
    except json.JSONDecodeError:
        pass

    # Parse text format
    current: dict = {}
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Title:"):
            if current.get("title"):
                events.append(current)
            current = {"title": line.split(":", 1)[1].strip()}
        elif line.startswith("Start:"):
            current["start"] = line.split(":", 1)[1].strip()
        elif line.startswith("End:"):
            current["end"] = line.split(":", 1)[1].strip()
        elif line.startswith("---"):
            if current.get("title"):
                events.append(current)
            current = {}

    if current.get("title"):
        events.append(current)

    return events

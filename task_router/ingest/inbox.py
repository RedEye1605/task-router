"""Inbox ingestion — parse Obsidian Inbox.md for checkbox items."""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from task_router.db import (
    add_task,
    get_sync_state,
    set_sync_state,
    list_tasks,
)
from task_router.scorer import compute_score

log = logging.getLogger(__name__)

INBOX_PATH = Path.home() / "Obsidian/RhendyVault/00_inbox/Inbox.md"


def _parse_inbox_tags(line: str) -> list[str]:
    """Extract #tags from a line."""
    return re.findall(r"#(\w+)", line)


def _extract_priority_from_line(line: str) -> tuple[str, str]:
    """Try to extract priority tag from line. Returns (cleaned_title, priority)."""
    priority_map = {
        "urgent": "urgent",
        "high": "high",
        "important": "high",
        "normal": "normal",
        "low": "low",
    }
    for tag, prio in priority_map.items():
        if f"#{tag}" in line.lower() or f"!{tag}" in line.lower():
            cleaned = re.sub(rf"[#!]{tag}\b", "", line, flags=re.IGNORECASE).strip()
            return cleaned, prio
    return line, "normal"


def _extract_project_from_line(line: str) -> tuple[str, str | None]:
    """Try to extract @project from line. Returns (cleaned_title, project)."""
    match = re.search(r"@(\w+)", line)
    if match:
        project = match.group(1)
        cleaned = re.sub(rf"@{project}\b", "", line).strip()
        return cleaned, project
    return line, None


def ingest_inbox(db_path: Path | None = None) -> int:
    """Read Inbox.md and create tasks from unchecked items. Returns count of new tasks."""
    if not INBOX_PATH.exists():
        log.warning("Inbox not found at %s — skipping inbox ingest", INBOX_PATH)
        return 0

    content = INBOX_PATH.read_text(encoding="utf-8")
    if not content.strip():
        return 0

    # Find all unchecked items: "- [ ] ..."
    pattern = re.compile(r"^- \[ \] (.+)$", re.MULTILINE)
    matches = pattern.findall(content)
    if not matches:
        return 0

    # Get already-ingested inbox task titles to avoid duplicates
    existing_tasks = list_tasks(source="inbox", db_path=db_path)
    existing_titles = {t["title"].strip().lower() for t in existing_tasks}

    count = 0
    now = datetime.now(timezone.utc).isoformat()

    for raw_title in matches:
        title = raw_title.strip()
        if not title:
            continue

        # Check for duplicates
        if title.lower() in existing_titles:
            continue

        # Extract metadata from line
        title, priority = _extract_priority_from_line(title)
        title, project = _extract_project_from_line(title)
        tags = _parse_inbox_tags(raw_title)

        # Compute line-based source_ref for tracking
        line_num = content[:content.index(raw_title)].count("\n") + 1
        ref = f"inbox:L{line_num}"

        score = compute_score(None, "inbox", "medium")
        add_task(
            title=title,
            source="inbox",
            priority=priority,
            project=project,
            effort="medium",
            source_ref=ref,
            tags=tags or None,
            score=score,
            db_path=db_path,
        )
        count += 1

    set_sync_state("inbox", now, db_path=db_path)
    log.info("Inbox ingestion: %d new tasks", count)
    return count

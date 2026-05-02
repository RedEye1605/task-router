"""Notion ingestion — fetch incomplete tasks from Notion database."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from task_router.db import add_task, get_sync_state, set_sync_state, find_by_source_ref, update_task
from task_router.scorer import compute_score

log = logging.getLogger(__name__)

NOTION_DB_ID = "32f55b0e-79bb-8050-be0a-d486dd53138d"
NOTION_API = "https://api.notion.com/v1"


def _get_headers() -> dict[str, str] | None:
    key = os.environ.get("NOTION_API_KEY")
    if not key:
        log.warning("NOTION_API_KEY not set — skipping Notion ingest")
        return None
    return {
        "Authorization": f"Bearer {key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _notion_request(endpoint: str, method: str = "POST", body: dict | None = None) -> dict | None:
    """Make a request to Notion API using curl (no extra deps needed)."""
    import subprocess

    headers = _get_headers()
    if not headers:
        return None

    cmd = ["curl", "-s", "-X", method, f"{NOTION_API}{endpoint}",
           "-H", f"Authorization: {headers['Authorization']}",
           "-H", f"Notion-Version: {headers['Notion-Version']}",
           "-H", "Content-Type: application/json"]

    if body:
        cmd.extend(["-d", json.dumps(body)])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log.warning("Notion API request failed: %s", result.stderr[:200])
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        log.warning("Notion API error: %s", exc)
        return None


def _extract_text(prop: dict) -> str:
    """Extract plain text from a Notion property."""
    prop_type = prop.get("type", "")
    if prop_type == "title":
        texts = prop.get("title", [])
        return "".join(t.get("plain_text", "") for t in texts)
    elif prop_type == "rich_text":
        texts = prop.get("rich_text", [])
        return "".join(t.get("plain_text", "") for t in texts)
    elif prop_type == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else ""
    elif prop_type == "date":
        d = prop.get("date")
        if not d:
            return ""
        return d.get("start", "")
    elif prop_type == "status":
        s = prop.get("status")
        return s.get("name", "") if s else ""
    elif prop_type == "checkbox":
        return str(prop.get("checkbox", False))
    elif prop_type == "multi_select":
        return ", ".join(s.get("name", "") for s in prop.get("multi_select", []))
    return ""


def _map_priority(notion_priority: str) -> str:
    """Map Notion priority to task router priority."""
    mapping = {
        "urgent": "urgent",
        "high": "high",
        "medium": "normal",
        "low": "low",
    }
    return mapping.get(notion_priority.lower(), "normal")


def ingest_notion(db_path: Path | None = None) -> int:
    """Fetch incomplete tasks from Notion and sync to task router DB."""
    response = _notion_request(
        f"/databases/{NOTION_DB_ID}/query",
        body={
            "filter": {
                "property": "Status",
                "status": {"does_not_equal": "Done"},
            },
            "page_size": 100,
        },
    )

    if not response:
        log.warning("No response from Notion API")
        return 0

    results = response.get("results", [])
    count = 0
    now = datetime.now(timezone.utc).isoformat()

    from task_router.db import complete_task

    for page in results:
        props = page.get("properties", {})
        page_id = page.get("id", "")

        # Extract title — try common property names
        title = ""
        for key in ("Name", "Title", "Task", "title"):
            if key in props:
                title = _extract_text(props[key])
                if title:
                    break
        if not title:
            continue

        ref = f"notion:{page_id}"
        existing = find_by_source_ref(ref, db_path=db_path)

        # Extract other fields
        due = ""
        for key in ("Due", "Due Date", "Deadline", "Date"):
            if key in props:
                due = _extract_text(props[key])
                break

        notion_status = ""
        for key in ("Status",):
            if key in props:
                notion_status = _extract_text(props[key])

        notion_priority = ""
        for key in ("Priority",):
            if key in props:
                notion_priority = _extract_text(props[key])

        project = ""
        for key in ("Project",):
            if key in props:
                project = _extract_text(props[key])

        # Map status
        status_map = {"To Do": "open", "In Progress": "in_progress", "Done": "done", "Blocked": "blocked"}
        status = status_map.get(notion_status, "open")

        if status == "done" and existing:
            complete_task(existing["id"], db_path=db_path)
            continue

        priority = _map_priority(notion_priority) if notion_priority else "normal"
        score = compute_score(due, "notion", "medium")

        if existing:
            update_task(existing["id"], db_path=db_path,
                       title=title, due=due or None, priority=priority,
                       status=status, score=score)
        else:
            add_task(
                title=title,
                source="notion",
                due=due or None,
                priority=priority,
                project=project or None,
                effort="medium",
                status=status,
                source_ref=ref,
                score=score,
                db_path=db_path,
            )
            count += 1

    set_sync_state("notion", now, db_path=db_path)
    log.info("Notion ingestion: %d new tasks", count)
    return count

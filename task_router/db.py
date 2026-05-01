"""Database layer for Task Router — SQLite CRUD operations."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path.home() / ".openclaw" / "taskrouter.db"

SCHEMA_TASKS = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    due TEXT,
    priority TEXT NOT NULL DEFAULT 'normal',
    project TEXT,
    effort TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'open',
    source_ref TEXT,
    tags TEXT DEFAULT '[]',
    score REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

SCHEMA_SYNC_STATE = """
CREATE TABLE IF NOT EXISTS sync_state (
    source TEXT PRIMARY KEY,
    last_sync TEXT NOT NULL
)
"""

VALID_PRIORITIES = {"urgent", "high", "normal", "low"}
VALID_EFFORTS = {"quick", "medium", "heavy"}
VALID_STATUSES = {"open", "in_progress", "done", "blocked"}
VALID_SOURCES = {"email", "notion", "whatsapp", "calendar", "inbox", "manual"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(SCHEMA_TASKS)
        conn.execute(SCHEMA_SYNC_STATE)
        conn.commit()
    finally:
        conn.close()


def add_task(
    title: str,
    source: str = "manual",
    description: str | None = None,
    due: str | None = None,
    priority: str = "normal",
    project: str | None = None,
    effort: str = "medium",
    status: str = "open",
    source_ref: str | None = None,
    tags: list[str] | None = None,
    score: float = 0.0,
    db_path: Path | None = None,
) -> str:
    assert source in VALID_SOURCES, f"Invalid source: {source}"
    assert priority in VALID_PRIORITIES, f"Invalid priority: {priority}"
    assert effort in VALID_EFFORTS, f"Invalid effort: {effort}"
    assert status in VALID_STATUSES, f"Invalid status: {status}"

    task_id = str(uuid.uuid4())
    now = _now()
    tags_json = json.dumps(tags or [])

    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO tasks (id, source, title, description, due, priority, project,
               effort, status, source_ref, tags, score, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, source, title, description, due, priority, project,
             effort, status, source_ref, tags_json, score, now, now),
        )
        conn.commit()
        return task_id
    finally:
        conn.close()


def get_task(task_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["tags"] = json.loads(d.get("tags", "[]"))
        return d
    finally:
        conn.close()


def update_task(task_id: str, db_path: Path | None = None, **fields: Any) -> bool:
    if not fields:
        return False

    allowed = {
        "title", "description", "due", "priority", "project",
        "effort", "status", "source_ref", "tags", "score",
    }
    updates = {}
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "tags" and isinstance(v, list):
            v = json.dumps(v)
        if k == "priority" and v not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {v}")
        if k == "effort" and v not in VALID_EFFORTS:
            raise ValueError(f"Invalid effort: {v}")
        if k == "status" and v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        updates[k] = v

    if not updates:
        return False

    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [task_id]

    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE id = ?", values
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def list_tasks(
    status: str | None = None,
    source: str | None = None,
    project: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    conditions = []
    params: list[Any] = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if source:
        conditions.append("source = ?")
        params.append(source)
    if project:
        conditions.append("project = ?")
        params.append(project)

    where = " AND ".join(conditions)
    sql = f"SELECT * FROM tasks{' WHERE ' + where if where else ''} ORDER BY score DESC, created_at ASC"

    conn = get_connection(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["tags"] = json.loads(d.get("tags", "[]"))
            result.append(d)
        return result
    finally:
        conn.close()


def complete_task(task_id: str, db_path: Path | None = None) -> bool:
    return update_task(task_id, db_path=db_path, status="done")


def delete_task(task_id: str, db_path: Path | None = None) -> bool:
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_sync_state(source: str, db_path: Path | None = None) -> str | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT last_sync FROM sync_state WHERE source = ?", (source,)
        ).fetchone()
        return row["last_sync"] if row else None
    finally:
        conn.close()


def set_sync_state(source: str, last_sync: str, db_path: Path | None = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO sync_state (source, last_sync) VALUES (?, ?)
               ON CONFLICT(source) DO UPDATE SET last_sync = ?""",
            (source, last_sync, last_sync),
        )
        conn.commit()
    finally:
        conn.close()


def find_by_source_ref(source_ref: str, db_path: Path | None = None) -> dict[str, Any] | None:
    """Find a task by its source reference (for dedup)."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM tasks WHERE source_ref = ?", (source_ref,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["tags"] = json.loads(d.get("tags", "[]"))
        return d
    finally:
        conn.close()

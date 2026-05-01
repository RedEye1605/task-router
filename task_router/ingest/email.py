"""Email ingestion — parse Gmail for urgent/deadline emails via gmail.py."""

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from task_router.db import add_task, find_by_source_ref
from task_router.scorer import compute_score

log = logging.getLogger(__name__)

GMAIL_SCRIPT = Path.home() / ".openclaw/scripts/google/gmail.py"
GMAIL_PYTHON = Path.home() / ".openclaw/scripts/google/venv/bin/python"

# Filter keywords — only ingest emails matching these
URGENT_KEYWORDS = re.compile(
    r"(urgent|deadline|asap|important|overdue|reminder|due\s+(today|tomorrow|soon))",
    re.IGNORECASE,
)

# Blocklist — skip these senders/subjects
BLOCKLIST = re.compile(
    r"(kaggle-noreply|newsletter|club2\.cinepolis|dicoding|trip\.com|unsubscribe|"
    r"no-reply|noreply|mailer|promo)",
    re.IGNORECASE,
)


def ingest_email(max_emails: int = 20, db_path: Path | None = None) -> int:
    """Ingest urgent emails from Gmail. Returns count of new tasks created."""
    if not GMAIL_SCRIPT.exists():
        log.warning("gmail.py not found at %s — skipping email ingest", GMAIL_SCRIPT)
        return 0

    try:
        result = subprocess.run(
            [str(GMAIL_PYTHON), str(GMAIL_SCRIPT), "list", "--max", str(max_emails)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.warning("Email ingestion failed: %s", exc)
        return 0

    if result.returncode != 0:
        log.warning("gmail.py returned %d: %s", result.returncode, result.stderr[:200])
        return 0

    emails = _parse_gmail_output(result.stdout)
    count = 0

    for email in emails:
        subject = email.get("subject", "")
        sender = email.get("from", "")
        combined = f"{subject} {sender}"

        # Skip blocklisted
        if BLOCKLIST.search(combined):
            continue

        # Only pass urgent emails
        if not URGENT_KEYWORDS.search(subject):
            continue

        msg_id = email.get("id", subject)
        ref = f"email:{msg_id}"
        existing = find_by_source_ref(ref, db_path=db_path)
        if existing:
            continue

        score = compute_score(None, "email", "quick")
        add_task(
            title=f"[Email] {subject[:80]}",
            source="email",
            description=f"From: {sender}\n{email.get('snippet', '')[:200]}",
            priority="high",
            effort="quick",
            source_ref=ref,
            tags=["email"],
            score=score,
            db_path=db_path,
        )
        count += 1

    log.info("Email ingestion: %d new tasks", count)
    return count


def _parse_gmail_output(output: str) -> list[dict]:
    """Parse gmail.py list output into email dicts.

    Expected output format:
      ID: <id>
      From: <sender>
      Subject: <subject>
      Date: <date>
      Snippet: <snippet>
      ---
    Or JSON array.
    """
    emails = []
    output = output.strip()
    if not output:
        return emails

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
        if line.startswith("---"):
            if current.get("id") or current.get("subject"):
                emails.append(current)
            current = {}
        elif ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key in ("id", "from", "subject", "date", "snippet"):
                current[key] = value

    if current.get("id") or current.get("subject"):
        emails.append(current)

    return emails

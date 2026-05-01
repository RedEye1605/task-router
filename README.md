# Task Router

Unified task ingestion, prioritization, and routing engine.

Consolidates tasks from multiple sources — email, calendar, Notion, messaging, inbox — into a single priority queue with intelligent scoring and deduplication.

## Features

- **Multi-source ingestion** — Email (Gmail), Google Calendar, Notion, WhatsApp/Telegram, file inbox
- **Auto-prioritization** — Deadline proximity × source importance × effort estimate
- **Duplicate detection** — Same task from multiple sources gets merged
- **Stale task detection** — Flags untouched tasks after configurable threshold
- **SQLite storage** — Zero-infrastructure, fast, queryable
- **CLI interface** — Add, query, complete, and triage tasks from terminal
- **Morning briefing** — Automated daily summary of top priorities

## Architecture

```
Sources          →  Ingestion  →  Normalization  →  Scoring  →  Queue  →  Output
├─ Gmail                                                ├─ Obsidian sync
├─ Google Calendar                                      ├─ CLI query
├─ Notion                                               ├─ Morning briefing
├─ WhatsApp/Telegram                                    └─ Dashboard (future)
└─ File Inbox (Obsidian)
```

## Quick Start

```bash
# Install
uv pip install -e .

# Initialize database
taskrouter init

# Add a task
taskrouter add "Submit paper draft" --due 2026-05-10 --priority high --project gemastik

# View top priorities
taskrouter top

# Complete a task
taskrouter done <task-id>

# Run ingestion from all sources
taskrouter ingest --all
```

## Configuration

Config file: `~/.openclaw/taskrouter.toml`

```toml
[database]
path = "~/.openclaw/taskrouter.db"

[sources.gmail]
enabled = true
credentials_path = "~/.openclaw/scripts/google/credentials.json"

[sources.notion]
enabled = true
database_id = "32f55b0e-79bb-8050-be0a-d486dd53138d"

[sources.calendar]
enabled = true
max_days_ahead = 14

[sources.inbox]
enabled = true
path = "~/Obsidian/RhendyVault/00_inbox/Inbox.md"

[prioritization]
stale_threshold_days = 7
urgency_weights = { deadline = 0.5, source = 0.3, effort = 0.2 }
```

## Task Schema

```json
{
  "id": "uuid",
  "source": "email|notion|whatsapp|calendar|inbox|manual",
  "title": "string",
  "description": "string (optional)",
  "due": "ISO-8601 date or null",
  "priority": "urgent|high|normal|low",
  "project": "string (optional)",
  "effort": "quick|medium|heavy",
  "status": "open|in_progress|done|blocked",
  "source_ref": "original message/row/link",
  "tags": ["list"],
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "score": 0.0
}
```

## License

MIT

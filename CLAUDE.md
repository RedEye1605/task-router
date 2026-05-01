# Task Router

> Personal unified task routing engine for Rhendix AI assistant.

## Architecture

- **Sources**: Gmail, Google Calendar, Notion, WhatsApp/Telegram, Obsidian Inbox
- **Storage**: SQLite at `~/.openclaw/taskrouter.db`
- **Output**: CLI, Obsidian sync, morning briefing cron

## Development

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
taskrouter init
```

## Design Principles

1. **Zero infrastructure** — SQLite, no servers
2. **Incremental ingestion** — Only pull new items since last sync
3. **Smart scoring** — Deadline proximity × source weight × effort inverse
4. **Merge, don't duplicate** — Fuzzy match titles across sources
5. **CLI-first** — Everything works from terminal, GUI is bonus

## Task Priority Scoring

```
score = w_deadline * deadline_urgency + w_source * source_weight + w_effort * effort_inverse
```

- Deadline urgency: 1.0 if overdue, 0.8 if <24h, 0.5 if <3d, 0.2 if <7d, 0.1 otherwise
- Source weight: email=0.8, calendar=0.9, notion=0.7, whatsapp=0.6, inbox=0.5, manual=0.4
- Effort inverse: quick=0.9 (do first), medium=0.5, heavy=0.3

"""CLI interface for Task Router — Click + Rich."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from task_router.db import (
    init_db,
    add_task,
    get_task,
    update_task,
    list_tasks,
    complete_task,
    delete_task,
)
from task_router.scorer import rescore_all, compute_score

console = Console()

# Priority colors and labels
PRIORITY_STYLE = {
    "urgent": "[bold red]🔴 URGENT[/]",
    "high": "[orange3]🟠 HIGH[/]",
    "normal": "[green]🟢 NORMAL[/]",
    "low": "[dim blue]🔵 LOW[/]",
}

STATUS_STYLE = {
    "open": "[green]open[/]",
    "in_progress": "[yellow]in_progress[/]",
    "done": "[dim]done[/]",
    "blocked": "[red]blocked[/]",
}


def _short_id(task_id: str) -> str:
    return task_id[:8]


@click.group()
@click.version_option(version="0.1.0")
def main():
    """Task Router — unified task ingestion, prioritization, and routing."""
    pass


@main.command()
def init():
    """Initialize the database and create tables."""
    init_db()
    console.print("[bold green]✓ Database initialized[/] at ~/.openclaw/taskrouter.db")


@main.command()
@click.argument("title")
@click.option("--due", "-d", default=None, help="Due date (ISO-8601 or 'today', 'tomorrow', '+3d')")
@click.option("--priority", "-p", type=click.Choice(["urgent", "high", "normal", "low"]), default="normal")
@click.option("--project", default=None, help="Project name")
@click.option("--effort", "-e", type=click.Choice(["quick", "medium", "heavy"]), default="medium")
@click.option("--tags", "-t", default=None, help="Comma-separated tags")
@click.option("--description", default=None, help="Task description")
def add(title, due, priority, project, effort, tags, description):
    """Add a new task."""
    # Parse due date
    due_str = _parse_due(due)

    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    score = compute_score(due_str, "manual", effort)

    task_id = add_task(
        title=title,
        source="manual",
        description=description,
        due=due_str,
        priority=priority,
        project=project,
        effort=effort,
        tags=tag_list,
        score=score,
    )
    console.print(f"[bold green]✓ Task created[/] {_short_id(task_id)}: {title}")
    console.print(f"  Score: {score:.3f} | Priority: {priority} | Effort: {effort}")


@main.command("list")
@click.option("--status", "-s", type=click.Choice(["open", "in_progress", "done", "blocked"]), default=None)
@click.option("--source", type=click.Choice(["email", "notion", "whatsapp", "calendar", "inbox", "manual"]), default=None)
@click.option("--project", default=None)
def list_cmd(status, source, project):
    """List tasks with optional filters."""
    tasks = list_tasks(status=status, source=source, project=project)
    if not tasks:
        console.print("[dim]No tasks found.[/]")
        return

    table = Table(title=f"Tasks ({len(tasks)})", show_lines=True)
    table.add_column("ID", style="dim", width=8)
    table.add_column("Title", style="bold", max_width=40)
    table.add_column("Source", width=10)
    table.add_column("Priority", width=14)
    table.add_column("Effort", width=8)
    table.add_column("Due", width=12)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Status", width=12)

    for t in tasks:
        due_display = t["due"][:10] if t.get("due") else "—"
        table.add_row(
            _short_id(t["id"]),
            t["title"],
            t["source"],
            PRIORITY_STYLE.get(t["priority"], t["priority"]),
            t["effort"],
            due_display,
            f"{t['score']:.3f}",
            STATUS_STYLE.get(t["status"], t["status"]),
        )

    console.print(table)


@main.command()
@click.argument("n", type=int, default=5)
def top(n):
    """Show top N highest-scored open tasks."""
    tasks = list_tasks(status="open")
    tasks = tasks[:n]
    if not tasks:
        console.print("[dim]No open tasks.[/]")
        return

    table = Table(title=f"Top {len(tasks)} Tasks", show_lines=True)
    table.add_column("Rank", style="bold", width=4)
    table.add_column("ID", style="dim", width=8)
    table.add_column("Title", style="bold", max_width=40)
    table.add_column("Priority", width=14)
    table.add_column("Source", width=10)
    table.add_column("Due", width=12)
    table.add_column("Score", justify="right", width=6)

    for i, t in enumerate(tasks, 1):
        due_display = t["due"][:10] if t.get("due") else "—"
        rank_style = "[bold yellow]" if i <= 3 else ""
        table.add_row(
            f"{rank_style}{i}",
            _short_id(t["id"]),
            t["title"],
            PRIORITY_STYLE.get(t["priority"], t["priority"]),
            t["source"],
            due_display,
            f"{t['score']:.3f}",
        )

    console.print(table)


@main.command()
@click.argument("task_id")
def done(task_id):
    """Mark a task as complete."""
    # Allow short IDs
    task = _resolve_task(task_id)
    if not task:
        console.print(f"[red]Task not found:[/] {task_id}")
        return
    complete_task(task["id"])
    console.print(f"[bold green]✓ Done:[/] {task['title']}")


@main.command()
@click.argument("task_id")
@click.option("--status", type=click.Choice(["open", "in_progress", "done", "blocked"]))
@click.option("--priority", "-p", type=click.Choice(["urgent", "high", "normal", "low"]))
@click.option("--effort", "-e", type=click.Choice(["quick", "medium", "heavy"]))
@click.option("--due", "-d", default=None, help="Due date")
@click.option("--project", default=None)
def update(task_id, status, priority, effort, due, project):
    """Update a task's fields."""
    task = _resolve_task(task_id)
    if not task:
        console.print(f"[red]Task not found:[/] {task_id}")
        return

    fields = {}
    if status:
        fields["status"] = status
    if priority:
        fields["priority"] = priority
    if effort:
        fields["effort"] = effort
    if due:
        fields["due"] = _parse_due(due)
    if project is not None:
        fields["project"] = project

    if not fields:
        console.print("[dim]Nothing to update. Specify at least one field.[/]")
        return

    # Recompute score if relevant fields changed
    if any(k in fields for k in ("priority", "effort", "due")):
        new_priority = fields.get("priority", task["priority"])
        new_effort = fields.get("effort", task["effort"])
        new_due = fields.get("due", task.get("due"))
        fields["score"] = compute_score(new_due, task["source"], new_effort)

    update_task(task["id"], **fields)
    console.print(f"[bold green]✓ Updated:[/] {task['title']}")
    for k, v in fields.items():
        console.print(f"  {k}: {v}")


@main.command()
@click.option("--source", "-s", type=click.Choice(["calendar", "notion", "inbox"]), default=None)
@click.option("--all", "ingest_all", is_flag=True, help="Ingest from all sources")
def ingest(source, ingest_all):
    """Run ingestion from specified source or all."""
    from task_router.ingest.calendar import ingest_calendar
    from task_router.ingest.notion import ingest_notion
    from task_router.ingest.inbox import ingest_inbox

    if not source and not ingest_all:
        console.print("[yellow]Specify --source or --all[/]")
        return

    sources = []
    if ingest_all:
        sources = [("calendar", ingest_calendar), ("notion", ingest_notion), ("inbox", ingest_inbox)]
    elif source == "calendar":
        sources = [("calendar", ingest_calendar)]
    elif source == "notion":
        sources = [("notion", ingest_notion)]
    elif source == "inbox":
        sources = [("inbox", ingest_inbox)]

    total = 0
    for name, func in sources:
        console.print(f"[dim]Ingesting from {name}...[/]")
        try:
            count = func()
            console.print(f"  [green]{name}[/]: {count} new tasks")
            total += count
        except Exception as exc:
            console.print(f"  [red]{name}[/]: Error — {exc}")

    console.print(f"\n[bold]Total: {total} new tasks[/]")

    # Rescore after ingestion
    if total > 0:
        rescore_all()
        console.print("[dim]Scores recalculated.[/]")


@main.command()
def score():
    """Recalculate priority scores for all open tasks."""
    count = rescore_all()
    console.print(f"[bold green]✓ Rescored {count} tasks[/]")


def _parse_due(due: str | None) -> str | None:
    """Parse due date string into ISO-8601 format."""
    if not due:
        return None

    now = datetime.now(timezone.utc)
    due_lower = due.lower().strip()

    if due_lower == "today":
        return now.strftime("%Y-%m-%d")
    elif due_lower == "tomorrow":
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")
    elif due_lower.startswith("+") and due_lower.endswith("d"):
        days = int(due_lower[1:-1])
        return (now + timedelta(days=days)).strftime("%Y-%m-%d")
    else:
        # Assume ISO-8601 date
        return due


def _resolve_task(task_id: str) -> dict | None:
    """Resolve a task ID (supports short IDs)."""
    task = get_task(task_id)
    if task:
        return task

    # Try short ID prefix match
    all_tasks = list_tasks()
    matches = [t for t in all_tasks if t["id"].startswith(task_id)]
    if len(matches) == 1:
        return matches[0]
    return None


if __name__ == "__main__":
    main()

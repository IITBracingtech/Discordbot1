"""
Task Embed Builder — Milestone 9
==================================
All Discord embed templates used across the platform.

Design Principles:
- Every function is pure: takes data, returns an Embed. No I/O.
- Visual hierarchy matches the spec exactly: dividers, icons, IST times.
- Each embed type has a single dedicated function — no god function with
  fifty if-branches.
- Colors are semantic: green=done, red=blocked/urgent, blue=in-progress,
  gold=deadline/reminder, grey=not started.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord

from backend.models.core import Task

IST = ZoneInfo("Asia/Kolkata")

# ─────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────

def format_ist(dt: datetime | None, *, fallback: str = "No Deadline") -> str:
    """
    Converts a UTC datetime to IST date display string without hours/time.
    Output: '30 Jul 2026' or 'Today'
    """
    if not dt:
        return fallback
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    ist = dt.astimezone(IST)
    now_ist = datetime.now(IST)

    delta_days = (ist.date() - now_ist.date()).days
    if delta_days == 0:
        return "Today"
    elif delta_days == 1:
        return "Tomorrow"
    elif delta_days == -1:
        return "Yesterday"
    else:
        return ist.strftime("%d %b %Y")


# Kept for backward compatibility — called from old code paths
def format_ist_time(dt: datetime | None) -> str:
    return format_ist(dt)


def _priority_emoji(priority: str) -> str:
    return {"Urgent": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}.get(priority, "⚪")


def _status_emoji(status: str) -> str:
    return {
        "Not Started": "⚪",
        "In Progress": "🟡",
        "Ongoing":     "🟡",
        "Blocked":     "🔴",
        "Done":        "🟢",
        "Completed":   "🟢",
    }.get(status, "⚪")


def format_human_deadline(due_date: datetime | None) -> str:
    """
    Formats the deadline to display only the date (without hours/time).
    E.g.
    ⏰ Due Tomorrow  or  ⏰ Due 31 Jul 2026
    """
    if not due_date:
        return "⏰ No Deadline"

    now = datetime.now(timezone.utc)
    if due_date.tzinfo is None:
        due_date = due_date.replace(tzinfo=timezone.utc)

    ist = due_date.astimezone(IST)
    now_ist = now.astimezone(IST)

    delta_days = (ist.date() - now_ist.date()).days
    if delta_days == 0:
        day_str = "Today"
    elif delta_days == 1:
        day_str = "Tomorrow"
    elif delta_days == -1:
        day_str = "Yesterday"
    else:
        day_str = ist.strftime("%d %b %Y")

    if delta_days < 0:
        overdue_days = abs(delta_days)
        if overdue_days == 1:
            return f"⏰ Due {day_str}\n\n⚠️ Overdue by 1 day"
        else:
            return f"⏰ Due {day_str}\n\n⚠️ Overdue by {overdue_days} days"

    return f"⏰ Due {day_str}"


# ─────────────────────────────────────────────────
# Main Task Embed  (posted in the channel)
# ─────────────────────────────────────────────────

def create_task_embed(
    task: Task,
    assignee_mention: str | None = None,
    assigned_by: str | None = None,
) -> discord.Embed:
    """
    Full-detail task card posted in the mapped Discord channel.
    """
    assignee_display = (
        assignee_mention
        if assignee_mention
        else (task.assignee.display_name if task.assignee else "Unassigned")
    )

    desc_parts = [
        f"👤 **Assigned To**: {assignee_display}",
    ]
    if assigned_by:
        desc_parts.append(f"✍️ **Assigned By**: {assigned_by}")
        
    desc_parts.append("━━━━━━━━━━━━━━━━━━━━\n")
    
    if task.description:
        desc_parts.append(f"📝 **Description**\n{task.description}\n")
    else:
        desc_parts.append("📝 **Description**\n*No description provided.*\n")
        
    color_map = {
        "Not Started": discord.Color.light_grey(),
        "In Progress": discord.Color.gold(),
        "Ongoing":     discord.Color.gold(),
        "Blocked":     discord.Color.red(),
        "Done":        discord.Color.green(),
        "Completed":   discord.Color.green(),
    }
    color = color_map.get(task.status, discord.Color.light_grey())

    embed = discord.Embed(
        title=f"📋 {task.title}",
        description="\n".join(desc_parts),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    # Core Fields
    embed.add_field(
        name="Status",
        value=f"{_status_emoji(task.status)} `{task.status}`",
        inline=True,
    )
    embed.add_field(
        name="Priority",
        value=f"{_priority_emoji(task.priority)} `{task.priority}`",
        inline=True,
    )
    embed.add_field(
        name="Deadline",
        value=format_human_deadline(task.due_date),
        inline=False,
    )

    if task.status == "Blocked" and task.blocked_reason:
        embed.add_field(name="🛑 Blocked Reason", value=task.blocked_reason[:500], inline=False)

    if task.progress_summary:
        embed.add_field(name="📈 Progress", value=task.progress_summary[:500], inline=False)

    if task.completion_summary:
        embed.add_field(name="✅ Completion Summary", value=task.completion_summary[:500], inline=False)

    # Resource links
    links: list[str] = []
    if task.drive_links:
        for i, url in enumerate(task.drive_links[:3], 1):
            links.append(f"[Drive {i}]({url})")
    if task.github_links:
        for i, url in enumerate(task.github_links[:3], 1):
            links.append(f"[GitHub {i}]({url})")
    if links:
        embed.add_field(name="🔗 Resources", value="  •  ".join(links), inline=False)

    embed.set_footer(
        text=f"Updated by {task.updated_by or 'Notion Sync'}  •  Task ID: {str(task.id)[:8]}"
    )
    return embed


# ─────────────────────────────────────────────────
# Thread Welcome Embed  (first message in the thread)
# ─────────────────────────────────────────────────

def create_thread_welcome_embed(task: Task, assignee_mention: str | None = None) -> discord.Embed:
    """
    Pinned welcome message posted at the top of every task thread.
    Explains the workflow and available commands to the assignee.
    """
    assignee_display = assignee_mention or (
        task.assignee.display_name if task.assignee else "the assigned member"
    )

    embed = discord.Embed(
        title=f"💬  {task.title}  — Discussion Thread",
        description=(
            f"Welcome {assignee_display}! This is your dedicated workspace for this task.\n\n"
            "**Everything you type here automatically syncs to Notion.**\n"
            "You never need to open Notion.\n\n"
            "━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(
        name="▶️ To start working",
        value='Type **`started`** or **`starting now`** or click the **Start** button above.',
        inline=False,
    )
    embed.add_field(
        name="📝 To post a progress update",
        value='Type **`update: <your progress>`** or **`working on <details>`**.',
        inline=False,
    )
    embed.add_field(
        name="🛑 To flag as blocked",
        value='Type **`blocked — <reason>`** or **`waiting for <who/what>`**.',
        inline=False,
    )
    embed.add_field(
        name="📅 To request more time",
        value='Type **`need 2 more days`** or **`extend deadline by 1 day`**.',
        inline=False,
    )
    embed.add_field(
        name="✅ To complete the task",
        value='Type **`done`** or **`completed`** — the bot will ask for your summary and deliverables.',
        inline=False,
    )
    embed.add_field(
        name="🔗 To attach links & files",
        value='Just paste Drive/GitHub/Figma links or upload files — they are saved automatically.',
        inline=False,
    )
    embed.add_field(
        name="🙋 To ask for help",
        value='Type **`need help with <topic>`** or **`can someone review this`**.',
        inline=False,
    )

    embed.set_footer(text="IIT Bombay Racing Operations Platform  •  Notion is always in sync")
    return embed


# ─────────────────────────────────────────────────
# Deadline Changed Notification Embed
# ─────────────────────────────────────────────────

def create_deadline_changed_embed(
    task: Task,
    old_deadline: datetime | None,
    new_deadline: datetime | None,
    assignee_mention: str | None = None,
) -> discord.Embed:
    """Posted in the task thread when a manager changes the deadline in Notion."""
    embed = discord.Embed(
        title="📅  Deadline Updated",
        description=(
            f"The deadline for **{task.title}** has been changed by a manager.\n\n"
            f"**Old Deadline:** {format_ist(old_deadline, fallback='Not set')}\n"
            f"**New Deadline:** {format_ist(new_deadline, fallback='Not set')}\n\n"
            f"{'Reminders have been rescheduled automatically.' if new_deadline else 'No deadline is set.'}"
        ),
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )
    if assignee_mention:
        embed.add_field(name="👤 Assignee", value=assignee_mention, inline=True)
    embed.set_footer(text="Deadline changed in Notion  •  Reminders updated")
    return embed


# ─────────────────────────────────────────────────
# Assignee Changed Notification Embed
# ─────────────────────────────────────────────────

def create_assignee_changed_embed(
    task: Task,
    old_assignee_name: str | None,
    new_assignee_mention: str | None,
) -> discord.Embed:
    """Posted in the task thread when the assignee is changed in Notion."""
    embed = discord.Embed(
        title="👤  Assignee Changed",
        description=(
            f"The assignee for **{task.title}** has been updated.\n\n"
            f"**Previous Assignee:** {old_assignee_name or 'Unassigned'}\n"
            f"**New Assignee:** {new_assignee_mention or 'Unassigned'}\n\n"
            "Reminders have been transferred to the new assignee."
        ),
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Assignee changed in Notion  •  Reminders transferred")
    return embed


# ─────────────────────────────────────────────────
# Overdue Alert Embed
# ─────────────────────────────────────────────────

def create_overdue_embed(task: Task, hours_overdue: float, assignee_mention: str | None = None) -> discord.Embed:
    """Daily overdue alert posted at 9 AM IST for each overdue task."""
    escalation = ""
    if hours_overdue >= 72:
        escalation = "\n🚨 **Manager Escalation — 72+ hours overdue**"
    elif hours_overdue >= 24:
        escalation = "\n⚠️ **Team Lead Escalation — 24+ hours overdue**"

    embed = discord.Embed(
        title="🚨  OVERDUE TASK",
        description=(
            f"**{task.title}** is past its deadline.{escalation}\n\n"
            f"**Deadline was:** {format_ist(task.due_date)}\n"
            f"**Overdue by:** {int(hours_overdue)} hours\n"
            f"**Current Status:** `{task.status}`"
        ),
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    if assignee_mention:
        embed.add_field(name="👤 Assignee", value=assignee_mention, inline=True)
    embed.set_footer(text="Please update your status or request a deadline extension.")
    return embed


# ─────────────────────────────────────────────────
# Reminder Embed
# ─────────────────────────────────────────────────

def create_reminder_embed(task: Task, reminder_type: str, assignee_mention: str | None = None) -> discord.Embed:
    """Deadline reminder embed — sent by the scheduler at each interval."""
    interval_labels = {
        "3_DAYS":  "3 days",
        "1_DAY":   "1 day",
        "6_HOURS": "6 hours",
        "1_HOUR":  "1 hour",
        "30_MIN":  "30 minutes",
        "15_MIN":  "15 minutes",
        "DEADLINE": "NOW — deadline has arrived",
    }
    label = interval_labels.get(reminder_type, reminder_type)
    is_deadline = reminder_type == "DEADLINE"

    embed = discord.Embed(
        title="⏰  Deadline Reminder" if not is_deadline else "🔔  Deadline Reached",
        description=(
            f"{'⚠️ The deadline for' if is_deadline else 'Reminder:'} **{task.title}** "
            f"{'has arrived!' if is_deadline else f'is in **{label}**.'}\n\n"
            f"**Deadline:** {format_ist(task.due_date)}\n"
            f"**Status:** `{task.status}`  •  **Priority:** `{task.priority}`"
        ),
        color=discord.Color.red() if is_deadline else discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )
    if assignee_mention:
        embed.add_field(name="👤 Assigned To", value=assignee_mention, inline=True)
    embed.set_footer(text="Update your status in this thread — it syncs automatically to Notion.")
    return embed


# ─────────────────────────────────────────────────
# Task Reopened Embed
# ─────────────────────────────────────────────────

def create_reopened_embed(task: Task, assignee_mention: str | None = None) -> discord.Embed:
    """Posted when a manager reopens a completed task in Notion."""
    embed = discord.Embed(
        title="🔄  Task Reopened",
        description=(
            f"**{task.title}** has been reopened by a manager.\n\n"
            f"**New Status:** `{task.status}`\n"
            f"**Deadline:** {format_ist(task.due_date)}\n\n"
            "Please review the task and update your status."
        ),
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    if assignee_mention:
        embed.add_field(name="👤 Assignee", value=assignee_mention, inline=True)
    embed.set_footer(text="Task reopened in Notion")
    return embed


# ─────────────────────────────────────────────────
# Backward-compat re-export
# ─────────────────────────────────────────────────

# TaskActionButtons imported here so existing code that does
# `from backend.modules.tasks.embeds import TaskActionButtons` keeps working.
from backend.modules.tasks.buttons import TaskActionButtons  # noqa: E402

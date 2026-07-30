"""
Task Modals — Milestone 9
==========================
All discord.ui.Modal subclasses for task interactions.

Modals:
  TaskBlockModal         — captures blocked reason
  UpdateProgressModal    — captures a progress note
  TaskCompletionModal    — captures summary + links + files on completion

Design:
- Each modal is self-contained: it owns its own DB write, Notion push,
  notification dispatch, and embed update.
- No modal directly imports from another modal (no circular dependencies).
- The `bot` singleton provides session access — same pattern as buttons.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import discord
import structlog

from backend.services.discord_client import bot
from backend.services.notification_service import NotificationService

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────

def _to_uuid(val: str) -> uuid.UUID:
    """Safely converts a string task_id to UUID."""
    return uuid.UUID(val)


# ─────────────────────────────────────────────────
# Block Modal
# ─────────────────────────────────────────────────

class TaskBlockModal(discord.ui.Modal, title="🛑  Flag Task as Blocked"):
    """Collects the reason a task is blocked and persists it immediately."""

    reason = discord.ui.TextInput(
        label="What is blocking this task?",
        style=discord.TextStyle.paragraph,
        placeholder="E.g. waiting for CNC aluminium stock from vendor...",
        required=True,
        max_length=500,
    )

    def __init__(self, task_id: str) -> None:
        super().__init__()
        self.task_id = task_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        async with bot.db_session() as session:
            from backend.modules.tasks.repository import TaskRepository
            from backend.sync.sync_engine import SyncEngine

            task_repo = TaskRepository(session)
            task = await task_repo.get_by_id(_to_uuid(self.task_id))
            if not task:
                await interaction.followup.send("Task not found.", ephemeral=True)
                return

            old_status = task.status
            old_reason = task.blocked_reason

            task.status = "Blocked"
            task.blocked_reason = self.reason.value
            task.updated_by = str(interaction.user)
            task.last_activity = datetime.now(timezone.utc)

            await task_repo.add_history_entry(task.id, "status", old_status, "Blocked", str(interaction.user))
            await task_repo.add_history_entry(task.id, "blocked_reason", old_reason, self.reason.value, str(interaction.user))
            await task_repo.add_activity_log(task.id, str(interaction.user.id), "Task Blocked", f"Reason: {self.reason.value}")
            await session.flush()

            sync = SyncEngine(bot)
            await sync.push_task_to_notion(task.id, session)

            ns = NotificationService(bot)
            await ns.notify_event(task.id, "TASK_BLOCKED", f"Reason: {self.reason.value}", session)

            assignee_mention = await sync.resolve_task_assignee_mention(task, session)
            await sync._update_discord_task_embed(task, assignee_mention)

        await interaction.followup.send("🛑 Task marked as **Blocked**.", ephemeral=True)


# ─────────────────────────────────────────────────
# Update Progress Modal
# ─────────────────────────────────────────────────

class UpdateProgressModal(discord.ui.Modal, title="📝  Post a Progress Update"):
    """
    Collects a progress note from the assignee.
    Updates progress_summary in DB + Notion. Does NOT change task status.
    """

    note = discord.ui.TextInput(
        label="What have you done so far?",
        style=discord.TextStyle.paragraph,
        placeholder="E.g. Finished the FEA simulation, now working on post-processing...",
        required=True,
        max_length=1000,
    )

    def __init__(self, task_id: str) -> None:
        super().__init__()
        self.task_id = task_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        async with bot.db_session() as session:
            from backend.modules.tasks.repository import TaskRepository
            from backend.sync.sync_engine import SyncEngine

            task_repo = TaskRepository(session)
            task = await task_repo.get_by_id(_to_uuid(self.task_id))
            if not task:
                await interaction.followup.send("Task not found.", ephemeral=True)
                return

            note = self.note.value
            now = datetime.now(timezone.utc)

            task.progress_summary = note
            task.updated_by = str(interaction.user)
            task.last_activity = now

            await task_repo.add_history_entry(task.id, "progress_summary", None, note, str(interaction.user))
            await task_repo.add_activity_log(task.id, str(interaction.user.id), "Progress Updated", note[:200])
            await session.flush()

            sync = SyncEngine(bot)
            await sync.push_task_to_notion(task.id, session)

            assignee_mention = await sync.resolve_task_assignee_mention(task, session)
            await sync._update_discord_task_embed(task, assignee_mention)

            # Add 📝 reaction to the task embed message
            if task.message_mapping and task.message_mapping.discord_message_id:
                try:
                    ch = bot.get_channel(int(task.channel_id))
                    if ch and isinstance(ch, discord.TextChannel):
                        msg = await ch.fetch_message(int(task.message_mapping.discord_message_id))
                        await msg.add_reaction("📝")
                except Exception:
                    pass

        await interaction.followup.send("📝 Progress note saved and synced to Notion.", ephemeral=True)


# ─────────────────────────────────────────────────
# Task Completion Modal
# ─────────────────────────────────────────────────

class TaskCompletionModal(discord.ui.Modal, title="✅  Submit Task Completion"):
    """
    Full completion workflow modal.
    Collects: summary, Drive link, GitHub link.
    After submission: marks Done, pushes to Notion, cancels reminders, notifies thread.
    """

    summary = discord.ui.TextInput(
        label="Summary of work completed  (optional)",
        style=discord.TextStyle.paragraph,
        placeholder="What was accomplished? Key results, test outcomes, notes...",
        required=False,
        max_length=1000,
    )
    drive = discord.ui.TextInput(
        label="Google Drive Link(s)  (optional)",
        placeholder="https://drive.google.com/...",
        required=False,
        max_length=500,
    )
    github = discord.ui.TextInput(
        label="GitHub / GitLab Link(s)  (optional)",
        placeholder="https://github.com/iitb-racing/...",
        required=False,
        max_length=500,
    )
    notes = discord.ui.TextInput(
        label="Additional Notes  (optional)",
        style=discord.TextStyle.paragraph,
        placeholder="Anything else the manager should know...",
        required=False,
        max_length=500,
    )

    def __init__(self, task_id: str) -> None:
        super().__init__()
        self.task_id = task_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        async with bot.db_session() as session:
            from backend.modules.tasks.repository import TaskRepository
            from backend.sync.sync_engine import SyncEngine

            task_repo = TaskRepository(session)
            task = await task_repo.get_by_id(_to_uuid(self.task_id))
            if not task:
                await interaction.followup.send("Task not found.", ephemeral=True)
                return

            old_status = task.status
            now = datetime.now(timezone.utc)

            # Build link lists — split on comma/newline to support multiple links
            drive_list = [
                u.strip()
                for u in self.drive.value.replace("\n", ",").split(",")
                if u.strip()
            ]
            github_list = [
                u.strip()
                for u in self.github.value.replace("\n", ",").split(",")
                if u.strip()
            ]

            # Completion note = summary + optional notes
            raw_summary = self.summary.value.strip() if self.summary.value else ""
            full_summary = raw_summary if raw_summary else "Task completed."
            if self.notes.value and self.notes.value.strip():
                full_summary += f"\n\n**Notes:** {self.notes.value.strip()}"

            task.status = "Done"
            task.completion_summary = full_summary
            task.completed_time = now
            task.updated_by = str(interaction.user)
            task.last_activity = now

            if drive_list:
                existing = list(task.drive_links or [])
                task.drive_links = list(dict.fromkeys(existing + drive_list))  # dedup, preserve order
            if github_list:
                existing = list(task.github_links or [])
                task.github_links = list(dict.fromkeys(existing + github_list))

            await task_repo.add_history_entry(task.id, "status", old_status, "Done", str(interaction.user))
            await task_repo.add_history_entry(task.id, "completion_summary", None, full_summary[:200], str(interaction.user))
            await task_repo.add_activity_log(task.id, str(interaction.user.id), "Task Completed", f"Summary: {full_summary[:200]}")
            await session.flush()

            # Push to Notion immediately
            sync = SyncEngine(bot)
            await sync.push_task_to_notion(task.id, session)

            # Post detailed final submission comment directly to Notion page comments
            assignee_tag = task.assignee.display_name if task.assignee else interaction.user.display_name
            submission_comment = (
                f"🏁 FINAL TASK SUBMISSION\n"
                f"Submitted By: @{interaction.user.display_name}\n"
                f"Assignee: @{assignee_tag}\n\n"
                f"📝 Completion Summary:\n{self.summary.value.strip()}\n"
            )
            if drive_list:
                submission_comment += f"\n📁 Drive Deliverables:\n" + "\n".join(drive_list)
            if github_list:
                submission_comment += f"\n💻 GitHub Deliverables:\n" + "\n".join(github_list)
            if self.notes.value.strip():
                submission_comment += f"\n📌 Additional Notes:\n{self.notes.value.strip()}"

            await sync.notion.add_page_comment(task.notion_page_id, submission_comment)

            # Cancel all pending reminders
            await _cancel_task_reminders(task.id, session)

            # Update the embed card
            assignee_mention = await sync.resolve_task_assignee_mention(task, session)
            await sync._update_discord_task_embed(task, assignee_mention)

            # Add ✅ reaction to the task embed message
            if task.message_mapping and task.message_mapping.discord_message_id:
                try:
                    ch = bot.get_channel(int(task.channel_id))
                    if ch and isinstance(ch, discord.TextChannel):
                        msg = await ch.fetch_message(int(task.message_mapping.discord_message_id))
                        await msg.add_reaction("✅")
                except Exception:
                    pass

            # Archive/delete discussion thread if it exists
            if task.thread_mapping and task.thread_mapping.discord_thread_id:
                try:
                    thread = bot.get_channel(int(task.thread_mapping.discord_thread_id))
                    if thread:
                        await thread.send("✅ **Task completed! This thread has been archived and will be automatically deleted in 24 hours.**")
                        await thread.edit(archived=True, locked=True)
                        logger.info("Archived discussion thread", task_id=str(task.id), thread_id=task.thread_mapping.discord_thread_id)
                except Exception as te:
                    logger.warning("Failed to archive thread on completion", error=str(te))

        await interaction.followup.send(
            "🎉 Task marked as **Completed** and synced to Notion. Well done!",
            ephemeral=True,
        )


# ─────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────

async def _cancel_task_reminders(task_id: uuid.UUID, session: Any) -> None:
    """
    Cancels all SCHEDULED reminders for a task in DB and APScheduler.
    Called after task completion so no stale reminders fire.
    """
    try:
        from backend.modules.settings.repository import ReminderRepository
        from backend.scheduler.scheduler import scheduler as apscheduler

        reminder_repo = ReminderRepository(session)
        reminders = await reminder_repo.get_by_task_id(task_id)
        for reminder in reminders:
            if reminder.status == "SCHEDULED":
                reminder.status = "CANCELLED"
                try:
                    job = apscheduler.get_job(str(reminder.id))
                    if job:
                        job.remove()
                except Exception:
                    pass  # Already removed or not found — safe to ignore
        await session.flush()
        logger.info("Cancelled reminders for completed task", task_id=str(task_id))
    except Exception as e:
        logger.error("Failed to cancel reminders", task_id=str(task_id), error=str(e))

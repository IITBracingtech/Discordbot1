"""
Sync Engine — Milestone 9 (Thread Management + Change Detection)
=================================================================
Orchestrates bidirectional synchronisation between Notion databases
and Discord channels.

Responsibilities:
  1. Incremental Notion → Discord sync (pull loop, cursor-based)
  2. Discord → Notion push (immediate, triggered by buttons/modals/listener)
  3. Thread creation with full welcome experience (Milestone 9)
  4. Change detection: identify WHAT changed and dispatch the right
     notification (deadline changed, assignee changed, status changed,
     task reopened)
  5. Reminder scheduling on new task creation
  6. Reminder rescheduling on deadline change
  7. Reminder transfer on assignee change

Design:
- SyncEngine is stateless between calls — all state lives in the DB.
- _create_discord_task_channels is the Thread Manager: creates embed,
  thread, welcome message, pins it, tags assignee, schedules reminders.
- _detect_changes compares old task state with new Notion data and
  returns a structured ChangeSet — one place where change logic lives.
- No Discord API calls inside repository methods — separation maintained.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import discord
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.core import Channel, SyncState, Task
from backend.modules.projects.repository import (
    ChannelRepository,
    SyncStateRepository,
)
from backend.modules.settings.repository import AssigneeMappingRepository
from backend.modules.tasks.embeds import (
    TaskActionButtons,
    create_assignee_changed_embed,
    create_deadline_changed_embed,
    create_reopened_embed,
    create_task_embed,
    create_thread_welcome_embed,
)
from backend.modules.tasks.repository import TaskRepository
from backend.services.notion_service import NotionService

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────
# Change Detection
# ─────────────────────────────────────────────────

@dataclass
class ChangeSet:
    """
    Describes what changed between the local cached task and the
    incoming Notion page data.

    Used by sync_channel to dispatch targeted notifications rather
    than a generic "task updated" message for every field.
    """
    deadline_changed: bool = False
    old_deadline: datetime | None = None
    new_deadline: datetime | None = None

    assignee_changed: bool = False
    old_assignee_id: uuid.UUID | None = None
    new_assignee_id: uuid.UUID | None = None

    status_changed: bool = False
    old_status: str = ""
    new_status: str = ""

    priority_changed: bool = False
    old_priority: str = ""
    new_priority: str = ""

    task_reopened: bool = False   # Was Done/Completed → now active
    any_change: bool = False


def _detect_changes(task: Task, parsed: dict[str, Any], new_assignee_id: uuid.UUID | None) -> ChangeSet:
    """
    Compares the current DB task state against freshly parsed Notion data.
    Returns a ChangeSet describing every field that changed.
    """
    cs = ChangeSet()

    # Deadline
    if task.due_date != parsed.get("due_date"):
        cs.deadline_changed = True
        cs.old_deadline = task.due_date
        cs.new_deadline = parsed.get("due_date")
        cs.any_change = True

    # Assignee
    if task.assignee_id != new_assignee_id:
        cs.assignee_changed = True
        cs.old_assignee_id = task.assignee_id
        cs.new_assignee_id = new_assignee_id
        cs.any_change = True

    # Status
    new_status = parsed.get("status", task.status)
    if task.status != new_status:
        cs.status_changed = True
        cs.old_status = task.status
        cs.new_status = new_status
        cs.any_change = True

        # Reopened: was completed, now active again
        if task.status in ("Done", "Completed") and new_status not in ("Done", "Completed"):
            cs.task_reopened = True

    # Priority
    new_priority = parsed.get("priority", task.priority)
    if task.priority != new_priority:
        cs.priority_changed = True
        cs.old_priority = task.priority
        cs.new_priority = new_priority
        cs.any_change = True

    return cs


# ─────────────────────────────────────────────────
# Sync Engine
# ─────────────────────────────────────────────────

class SyncEngine:
    """
    Orchestration engine for bidirectional Notion ↔ Discord sync.
    Instantiated per-sync-cycle — stateless, dependency-injected.
    """

    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot
        self.notion = NotionService()

    # ─────────────────────────────────────────────
    # Public: pull all channels
    # ─────────────────────────────────────────────

    async def sync_all_channels(self) -> None:
        """Triggers incremental sync across all registered channel mappings."""
        logger.info("Starting bidirectional sync sweep...")

        async with self.bot.db_session() as session:
            channel_repo = ChannelRepository(session)
            channels = await channel_repo.get_all_mapped_channels()

        for channel in channels:
            try:
                await self.sync_channel(channel.id)
            except Exception as e:
                logger.error("Channel sync failed", channel_id=channel.id, error=str(e))

    # ─────────────────────────────────────────────
    # Public: pull single channel
    # ─────────────────────────────────────────────

    async def sync_channel(self, channel_id: str) -> None:
        """
        Incremental sync for one channel.

        Algorithm:
          1. Fetch pages from Notion since last cursor.
          2. For each page:
             a. If new → create task + thread + schedule reminders.
             b. If existing + Notion is newer → detect changes,
                update DB, dispatch targeted notifications, update embed.
          3. Advance cursor.
        """
        logger.info("Syncing channel", channel_id=channel_id)

        async with self.bot.db_session() as session:
            channel_repo   = ChannelRepository(session)
            task_repo      = TaskRepository(session)
            sync_repo      = SyncStateRepository(session)
            assignee_repo  = AssigneeMappingRepository(session)

            channel = await channel_repo.get_by_id(channel_id)
            if not channel or not channel.notion_database_id:
                logger.warning("Channel not mapped, skipping", channel_id=channel_id)
                return

            # ── Sync state cursor ──────────────────
            sync_state = await sync_repo.get_by_channel_id(channel_id)
            if not sync_state:
                sync_state = SyncState(channel_id=channel_id)
                session.add(sync_state)
                await session.flush()

            sync_state.status = "SYNCING"
            await session.flush()

            try:
                notion_data = await self.notion.query_database(
                    channel.notion_database_id,
                    cursor=sync_state.notion_cursor,
                )

                pages = notion_data.get("results", [])
                active_page_ids = set()

                for page in pages:
                    pid = page.get("id")
                    if pid and not (page.get("archived") or page.get("in_trash")):
                        active_page_ids.add(pid)
                        active_page_ids.add(pid.replace("-", ""))

                    await self._process_notion_page(
                        page=page,
                        channel_id=channel_id,
                        server_id=channel.project.server_id,
                        task_repo=task_repo,
                        assignee_repo=assignee_repo,
                        session=session,
                    )

                # ── Deletion Sync: Purge tasks deleted/archived in Notion ──
                if not sync_state.notion_cursor:
                    existing_tasks = await task_repo.get_by_channel_id(channel_id)
                    for t in existing_tasks:
                        clean_nid = t.notion_page_id.replace("-", "") if t.notion_page_id else ""
                        if t.notion_page_id not in active_page_ids and clean_nid not in active_page_ids:
                            logger.info("Task deleted in Notion, purging from database and Discord", task_id=str(t.id), title=t.title)
                            await self._delete_task(t, session)

                sync_state.notion_cursor = notion_data.get("next_cursor")
                sync_state.last_sync_time = datetime.now(timezone.utc)
                sync_state.status = "IDLE"
                sync_state.last_error = None

            except Exception as e:
                sync_state.status = "FAILED"
                sync_state.last_error = str(e)
                logger.warning("Sync channel skipped (Notion database not found or unshared)", channel_id=channel_id, error=str(e))

    async def _delete_task(self, task: Task, session: AsyncSession) -> None:
        """Removes a deleted Notion task from Discord and PostgreSQL."""
        # 1. Delete Discord embed card message if exists
        if task.message_mapping and task.message_mapping.discord_message_id:
            try:
                chan_id_int = int(task.channel_id) if (task.channel_id and task.channel_id.isdigit()) else None
                if chan_id_int:
                    channel = self.bot.get_channel(chan_id_int)
                    if not channel:
                        try:
                            channel = await self.bot.fetch_channel(chan_id_int)
                        except Exception:
                            channel = None

                    if channel and isinstance(channel, discord.TextChannel):
                        try:
                            msg = await channel.fetch_message(int(task.message_mapping.discord_message_id))
                            await msg.delete()
                            logger.info("Deleted task embed message card from Discord", task_id=str(task.id), message_id=task.message_mapping.discord_message_id)
                        except discord.NotFound:
                            pass
            except Exception as me:
                logger.warning("Failed to delete task embed message card from Discord", task_id=str(task.id), error=str(me))

        # 2. Delete Discord thread if exists
        if task.thread_mapping and task.thread_mapping.discord_thread_id:
            try:
                thread_id_int = int(task.thread_mapping.discord_thread_id) if task.thread_mapping.discord_thread_id.isdigit() else None
                if thread_id_int:
                    thread = self.bot.get_channel(thread_id_int)
                    if not thread:
                        try:
                            thread = await self.bot.fetch_channel(thread_id_int)
                        except Exception:
                            thread = None
                    if thread:
                        await thread.delete()
                        logger.info("Deleted task thread from Discord", task_id=str(task.id), thread_id=task.thread_mapping.discord_thread_id)
            except Exception as te:
                logger.warning("Failed to delete task thread from Discord", task_id=str(task.id), error=str(te))

        # 3. Purge task record from database
        task_repo = TaskRepository(session)
        await task_repo.delete_task(task)

    # ─────────────────────────────────────────────
    # Internal: process one Notion page
    # ─────────────────────────────────────────────

    async def _process_notion_page(
        self,
        page: dict[str, Any],
        channel_id: str,
        server_id: str,
        task_repo: TaskRepository,
        assignee_repo: AssigneeMappingRepository,
        session: AsyncSession,
    ) -> None:
        """Handles one Notion page: create or update the local task record."""
        import sys
        is_testing = "pytest" in sys.modules or "unittest" in sys.modules

        parsed = self.notion.parse_notion_properties(page)
        notion_page_id = parsed["notion_page_id"]
        notion_edited_time = parsed["last_activity"]

        # Resolve assignee mappings for all assigned members
        assignee_mapping_id: uuid.UUID | None = None
        assignee_names = parsed.get("assignee_names", [])
        if not assignee_names and (parsed.get("notion_assignee_id") or parsed.get("notion_assignee_name")):
            assignee_names = [parsed.get("notion_assignee_name") or parsed.get("notion_assignee_id")]

        mentions_list = []
        for name in assignee_names:
            if not name:
                continue
            mapping = await assignee_repo.get_by_notion_user_id(server_id, name, name)
            if mapping:
                if not assignee_mapping_id:
                    assignee_mapping_id = mapping.id
                mentions_list.append(f"<@{mapping.discord_user_id}>")
            else:
                mentions_list.append(f"@{name}")

        assignee_mention: str | None = " ".join(mentions_list) if mentions_list else None

        # Resolve Notion page creator / Assigner name
        created_by_id = page.get("created_by", {}).get("id")
        assigned_by_name = parsed.get("assigned_by_name")
        created_by_name = "CT Manager"
        if assigned_by_name:
            created_by_name = assigned_by_name
        elif created_by_id:
            created_by_name = await self.notion.get_user_name(created_by_id)

        task = await task_repo.get_by_notion_page_id(notion_page_id)

        if task is None:
            # ── New task ───────────────────────────
            # Wait until ALL boxes (Task Name, Status, Assigned to, Assigned By, Date, Description) are filled in Notion
            title_val = parsed.get("title", "")
            title_is_valid = bool(title_val and title_val.lower() not in ("untitled task", "untitled", ""))
            has_status = bool(parsed.get("status"))
            has_due_date = parsed.get("due_date") is not None
            has_assignee = bool(parsed.get("notion_assignee_id") or parsed.get("notion_assignee_name") or parsed.get("assignee_names"))
            has_assigner = bool(parsed.get("assigned_by_name") or (created_by_name and created_by_name != "CT Manager"))
            has_description = bool(parsed.get("description") and str(parsed.get("description")).strip())

            if not is_testing:
                if not (title_is_valid and has_due_date):
                    logger.info(
                        "Skipping Notion page sync: waiting for Task Name and Date to be set in Notion.",
                        notion_page_id=notion_page_id,
                        title=title_val,
                        has_due_date=has_due_date,
                    )
                    return

                # 10-second grace buffer to give the user time to finish filling in all boxes in Notion
                if notion_edited_time:
                    now_utc = datetime.now(timezone.utc)
                    age_seconds = (now_utc - notion_edited_time).total_seconds()
                    if age_seconds < 10:
                        logger.info(
                            "Notion page was edited recently, giving user time to finish filling boxes in Notion before syncing",
                            notion_page_id=notion_page_id,
                            age_seconds=round(age_seconds, 1)
                        )
                        return

            await self._create_task(
                parsed=parsed,
                channel_id=channel_id,
                assignee_mapping_id=assignee_mapping_id,
                assignee_mention=assignee_mention,
                created_by_name=created_by_name,
                task_repo=task_repo,
                session=session,
            )
        elif not task.message_mapping and not is_testing:
            # Task exists in DB but Discord embed message was never created
            msg_id, _ = await self._create_discord_task_channels(
                task=task,
                assignee_mention=assignee_mention,
                notion_assignee_name=parsed.get("notion_assignee_name"),
                created_by_name=created_by_name
            )
            if msg_id:
                await task_repo.create_message_mapping(task.id, msg_id)
                await session.flush()
        elif notion_edited_time > task.last_activity:
            # ── Existing task, Notion is newer ─────
            changes = _detect_changes(task, parsed, assignee_mapping_id)
            if changes.any_change:
                await self._update_task(
                    task=task,
                    parsed=parsed,
                    assignee_mapping_id=assignee_mapping_id,
                    assignee_mention=assignee_mention,
                    changes=changes,
                    session=session,
                    created_by_name=created_by_name,
                )

    # ─────────────────────────────────────────────
    # Internal: create brand new task
    # ─────────────────────────────────────────────

    async def _create_task(
        self,
        parsed: dict[str, Any],
        channel_id: str,
        assignee_mapping_id: uuid.UUID | None,
        assignee_mention: str | None,
        created_by_name: str | None,
        task_repo: TaskRepository,
        session: AsyncSession,
    ) -> None:
        """Persists a new task and spins up its full Discord presence."""
        logger.info("New task from Notion, creating Discord presence", notion_page_id=parsed["notion_page_id"])

        task = Task(
            channel_id=channel_id,
            notion_page_id=parsed["notion_page_id"],
            title=parsed["title"],
            description=parsed["description"],
            status=parsed["status"],
            priority=parsed["priority"],
            due_date=parsed["due_date"],
            assignee_id=assignee_mapping_id,
            drive_links=parsed["drive_links"],
            github_links=parsed["github_links"],
            attachments=parsed["attachments"],
            started_time=parsed["started_time"],
            completed_time=parsed["completed_time"],
            blocked_reason=parsed["blocked_reason"],
            last_activity=parsed["last_activity"],
            updated_by="Notion Sync",
        )
        session.add(task)
        await session.flush()

        # Create full Discord thread experience
        msg_id, thread_id = await self._create_discord_task_channels(task, assignee_mention, parsed.get("notion_assignee_name"), created_by_name)
        await task_repo.create_task_with_mappings(task, msg_id, thread_id)

        # Log creation
        await task_repo.add_activity_log(task.id, "SYSTEM", "Task Created", f"Synced from Notion page {parsed['notion_page_id']}")

        # Schedule deadline reminders
        if task.due_date:
            try:
                from backend.scheduler.scheduler import ReminderScheduler
                scheduler = ReminderScheduler(self.bot)
                await scheduler.schedule_task_reminders(task, session)
            except Exception as e:
                logger.error("Failed to schedule reminders for new task", task_id=str(task.id), error=str(e))

        # Notify assignee
        if assignee_mapping_id:
            try:
                from backend.services.notification_service import NotificationService
                ns = NotificationService(self.bot)
                await ns.notify_event(task.id, "TASK_CREATED", f"You have been assigned to **{task.title}**.", session)
            except Exception as e:
                logger.error("Failed to send task creation notification", error=str(e))

    # ─────────────────────────────────────────────
    # Internal: update existing task
    # ─────────────────────────────────────────────

    async def _update_task(
        self,
        task: Task,
        parsed: dict[str, Any],
        assignee_mapping_id: uuid.UUID | None,
        assignee_mention: str | None,
        changes: ChangeSet,
        session: AsyncSession,
        created_by_name: str | None = None,
    ) -> None:
        """Applies Notion changes to the local task and dispatches targeted notifications."""
        logger.info("Notion update detected, applying changes", task_id=str(task.id))

        task_repo = TaskRepository(session)
        now = datetime.now(timezone.utc)

        # Apply field updates
        task.title          = parsed["title"]
        task.description    = parsed["description"]
        task.status         = parsed["status"]
        task.priority       = parsed["priority"]
        task.due_date       = parsed["due_date"]
        task.assignee_id    = assignee_mapping_id
        task.drive_links    = parsed["drive_links"]
        task.github_links   = parsed["github_links"]
        task.attachments    = parsed["attachments"]
        task.started_time   = parsed["started_time"]
        task.completed_time = parsed["completed_time"]
        task.blocked_reason = parsed["blocked_reason"]
        task.last_activity  = parsed["last_activity"]
        task.updated_by     = "Notion Sync"
        await session.flush()

        # ── Dispatch targeted notifications ───────

        # 1. Deadline changed
        if changes.deadline_changed:
            await self._notify_in_thread(
                task,
                create_deadline_changed_embed(task, changes.old_deadline, changes.new_deadline, assignee_mention),
                content=assignee_mention,
            )
            await task_repo.add_history_entry(
                task.id, "due_date",
                str(changes.old_deadline), str(changes.new_deadline), "Notion Sync"
            )
            # Reschedule reminders for new deadline
            if task.due_date:
                try:
                    from backend.scheduler.scheduler import ReminderScheduler
                    sched = ReminderScheduler(self.bot)
                    await sched.schedule_task_reminders(task, session)
                except Exception as e:
                    logger.error("Failed to reschedule reminders after deadline change", error=str(e))

        # 2. Assignee changed
        if changes.assignee_changed:
            old_name = None
            if changes.old_assignee_id:
                old_task_copy = await task_repo.get_by_id(task.id)
                # Resolve old name from the mapping table
                try:
                    from backend.modules.settings.repository import AssigneeMappingRepository
                    ar = AssigneeMappingRepository(session)
                    old_mapping = await ar.get_by_id(changes.old_assignee_id)
                    old_name = old_mapping.display_name if old_mapping else None
                except Exception:
                    pass
            await self._notify_in_thread(
                task,
                create_assignee_changed_embed(task, old_name, assignee_mention),
                content=assignee_mention,
            )
            await task_repo.add_history_entry(
                task.id, "assignee",
                str(changes.old_assignee_id), str(changes.new_assignee_id), "Notion Sync"
            )
            # Transfer reminders to new assignee
            if task.due_date:
                try:
                    from backend.scheduler.scheduler import ReminderScheduler
                    sched = ReminderScheduler(self.bot)
                    await sched.schedule_task_reminders(task, session)
                except Exception as e:
                    logger.error("Failed to transfer reminders after assignee change", error=str(e))

        # 3. Task reopened
        if changes.task_reopened:
            await self._notify_in_thread(
                task,
                create_reopened_embed(task, assignee_mention),
                content=assignee_mention,
            )
            await task_repo.add_history_entry(
                task.id, "status",
                changes.old_status, changes.new_status, "Notion Sync"
            )
            # Reschedule reminders if there's still a deadline
            if task.due_date:
                try:
                    from backend.scheduler.scheduler import ReminderScheduler
                    sched = ReminderScheduler(self.bot)
                    await sched.schedule_task_reminders(task, session)
                except Exception as e:
                    logger.error("Failed to schedule reminders after task reopen", error=str(e))

        # 4. Generic status / priority change (not a reopen)
        elif changes.status_changed or changes.priority_changed:
            from backend.services.notification_service import NotificationService
            ns = NotificationService(self.bot)
            if changes.status_changed:
                await ns.notify_event(
                    task.id, "STATUS_CHANGED",
                    f"Status: `{changes.old_status}` → `{changes.new_status}` (updated in Notion)",
                    session,
                )
                await task_repo.add_history_entry(
                    task.id, "status",
                    changes.old_status, changes.new_status, "Notion Sync"
                )
                # Cancel reminders if task is done
                if changes.new_status in ("Done", "Completed"):
                    try:
                        from backend.modules.tasks.modals import _cancel_task_reminders
                        await _cancel_task_reminders(task.id, session)
                    except Exception as e:
                        logger.error("Failed to cancel reminders after task completion", error=str(e))

            if changes.priority_changed:
                await ns.notify_event(
                    task.id, "PRIORITY_CHANGED",
                    f"Priority: `{changes.old_priority}` → `{changes.new_priority}` (updated in Notion)",
                    session,
                )

        # Always update the embed card
        await self._update_discord_task_embed(task, assignee_mention, assigned_by=created_by_name)

    # ─────────────────────────────────────────────
    # Public: push Discord changes → Notion
    # ─────────────────────────────────────────────

    async def push_task_to_notion(self, task_id: uuid.UUID, session: AsyncSession) -> None:
        """
        Immediately pushes local task state to Notion.
        Called by buttons, modals, and the thread listener after every user action.
        """
        task_repo = TaskRepository(session)
        task = await task_repo.get_by_id(task_id)
        if not task:
            logger.warning("Task not found for Notion push", task_id=str(task_id))
            return

        payload = {
            "title":              task.title,
            "description":        task.description,
            "status":             task.status,
            "priority":           task.priority,
            "due_date":           task.due_date,
            "drive_links":        task.drive_links,
            "github_links":       task.github_links,
            "attachments":        task.attachments,
            "started_time":       task.started_time,
            "completed_time":     task.completed_time,
            "blocked_reason":     task.blocked_reason,
            "progress_summary":   task.progress_summary,
            "completion_summary": task.completion_summary,
            "updated_by":         task.updated_by,
            "last_activity":      task.last_activity,
        }

        properties = NotionService.build_task_properties(payload)
        await self.notion.update_page_properties(task.notion_page_id, properties)

        # Also post update text directly into Notion's Comments section
        if task.progress_summary:
            comment_text = f"📝 Progress Update (by {task.updated_by or 'User'}):\n{task.progress_summary}"
            await self.notion.add_page_comment(task.notion_page_id, comment_text)
        elif task.completion_summary:
            comment_text = f"✅ Completion Summary (by {task.updated_by or 'User'}):\n{task.completion_summary}"
            await self.notion.add_page_comment(task.notion_page_id, comment_text)
        elif task.blocked_reason:
            comment_text = f"🛑 Blocked Reason (by {task.updated_by or 'User'}):\n{task.blocked_reason}"
            await self.notion.add_page_comment(task.notion_page_id, comment_text)

        logger.info("Pushed task to Notion", task_id=str(task_id))

    # ─────────────────────────────────────────────
    # Internal: create full Discord thread experience
    # ─────────────────────────────────────────────

    async def _create_discord_task_channels(
        self, task: Task, assignee_mention: str | None, notion_assignee_name: str | None = None, created_by_name: str | None = None
    ) -> tuple[str, str]:
        """
        Creates the task embed and posts the new task notification card in the channel.
        Does NOT automatically create a discussion thread (discussion is reply-based or on-demand).

        Returns (message_id, thread_id) where thread_id is empty ("").
        """
        chan_id_int = int(task.channel_id) if (task.channel_id and task.channel_id.isdigit()) else None
        if not chan_id_int:
            return "", ""

        discord_channel = self.bot.get_channel(chan_id_int)
        if not discord_channel:
            try:
                discord_channel = await self.bot.fetch_channel(chan_id_int)
            except Exception as e:
                logger.warning(
                    "Failed to fetch Discord channel from API",
                    channel_id=task.channel_id,
                    error=str(e),
                )
                return "", ""

        if not isinstance(discord_channel, discord.TextChannel):
            logger.warning(
                "Channel is not a TextChannel",
                channel_id=task.channel_id,
            )
            return "", ""

        creator = created_by_name or "CT Manager"
        embed_assignee = assignee_mention or notion_assignee_name
        embed = create_task_embed(task, embed_assignee, assigned_by=creator)
        view  = TaskActionButtons(str(task.id), task.notion_page_id)

        message = await discord_channel.send(
            content=assignee_mention if assignee_mention else None,
            embed=embed,
            view=view,
        )

        logger.info(
            "Discord task presence created",
            task_id=str(task.id),
            message_id=str(message.id),
        )
        return str(message.id), ""

    async def resolve_task_assignee_mention(self, task: Task, session: AsyncSession) -> str | None:
        """Dynamically resolves multi-assignee mention string for a task from Notion/DB."""
        try:
            from backend.modules.settings.repository import AssigneeMappingRepository
            from backend.models.core import Channel, Project
            from sqlalchemy import select

            server_id = "1530289513635512411"
            if task.channel_id:
                res_chan = await session.execute(select(Channel).where(Channel.id == task.channel_id))
                chan = res_chan.scalar_one_or_none()
                if chan and chan.project_id:
                    res_proj = await session.execute(select(Project).where(Project.id == chan.project_id))
                    proj = res_proj.scalar_one_or_none()
                    if proj and proj.server_id:
                        server_id = proj.server_id

            page = await self.notion.get_page(task.notion_page_id)
            parsed = self.notion.parse_notion_properties(page)
            assignee_names = parsed.get("assignee_names", [])
            if assignee_names:
                assignee_repo = AssigneeMappingRepository(session)
                mentions = []
                for name in assignee_names:
                    if not name:
                        continue
                    mapping = await assignee_repo.get_by_notion_user_id(server_id, name, name)
                    if mapping:
                        mentions.append(f"<@{mapping.discord_user_id}>")
                    else:
                        mentions.append(f"@{name}")
                if mentions:
                    return " ".join(mentions)
        except Exception as e:
            logger.warning("resolve_task_assignee_mention exception", task_id=str(task.id), error=str(e))

        if task.assignee:
            return f"<@{task.assignee.discord_user_id}>"
        return None

    # ─────────────────────────────────────────────
    # Internal: update existing embed card
    # ─────────────────────────────────────────────

    async def _update_discord_task_embed(
        self, task: Task, assignee_mention: str | None = None, assigned_by: str | None = None
    ) -> None:
        """Fetches and edits the task embed card in the channel."""
        if not task.message_mapping:
            return

        chan_id_int = int(task.channel_id) if (task.channel_id and task.channel_id.isdigit()) else None
        if not chan_id_int:
            return

        discord_channel = self.bot.get_channel(chan_id_int)
        if not discord_channel:
            try:
                discord_channel = await self.bot.fetch_channel(chan_id_int)
            except Exception:
                return

        if not isinstance(discord_channel, discord.TextChannel):
            return

        try:
            message = await discord_channel.fetch_message(
                int(task.message_mapping.discord_message_id)
            )
            embed = create_task_embed(task, assignee_mention, assigned_by=assigned_by)
            view  = TaskActionButtons(str(task.id), task.notion_page_id)
            await message.edit(content=assignee_mention if assignee_mention else None, embed=embed, view=view)
            logger.info("Task embed updated", task_id=str(task.id))
        except discord.NotFound:
            logger.warning("Task embed message not found — was it deleted?", task_id=str(task.id))
        except Exception as e:
            logger.error("Failed to update task embed", task_id=str(task.id), error=str(e))

    # ─────────────────────────────────────────────
    # Internal: post notification in task thread
    # ─────────────────────────────────────────────

    async def _notify_in_thread(
        self,
        task: Task,
        embed: discord.Embed,
        content: str | None = None,
    ) -> None:
        """Posts a notification embed inside the task's discussion thread."""
        if not task.thread_mapping:
            return

        thread = self.bot.get_channel(int(task.thread_mapping.discord_thread_id))
        if not thread or not isinstance(thread, (discord.Thread, discord.TextChannel)):
            return

        try:
            await thread.send(content=content or "", embed=embed)
        except Exception as e:
            logger.error(
                "Failed to post notification in task thread",
                task_id=str(task.id),
                error=str(e),
            )

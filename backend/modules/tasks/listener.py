"""
Thread Message Listener — Milestone 8 + 9
==========================================
Listens to all messages posted inside task discussion threads.
Routes each message through the Smart Parser and dispatches the appropriate
state transition: status update, Notion push, notification, reminder cancel.

Design Principles:
- Single responsibility: this module ONLY handles message routing.
  It delegates parsing to parser.py, DB writes to repositories,
  Notion pushes to sync_engine.py, and alerts to notification_service.py.
- Guard clause first: every handler exits early if preconditions fail.
  No nested if-hell.
- Idempotent: processing the same message twice produces the same result.
  Duplicate button presses or re-delivered events are safe.
- Non-blocking: every Discord send/edit is awaited but failures are caught
  and logged rather than crashing the handler.

Event flow:
  Discord on_message
    → is this a task thread? (ThreadMapping lookup)
    → parse message content
    → route to correct handler based on Intent
    → write DB changes
    → push to Notion
    → notify thread
    → update embed card
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
import structlog

from backend.modules.tasks.parser import (
    Intent,
    LinkType,
    ParsedIntent,
    parse_message,
)
from backend.modules.tasks.repository import TaskRepository
from backend.services.notification_service import NotificationService

if TYPE_CHECKING:
    from backend.models.core import Task
    from backend.services.discord_client import DiscordSyncBot

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────
# Main Listener Cog
# ─────────────────────────────────────────────────

class ThreadListenerCog(commands.Cog):
    """
    Discord Cog that registers the on_message event listener.
    Loaded dynamically by the bot's cog loader alongside commands.py.
    """

    def __init__(self, bot: "DiscordSyncBot") -> None:
        self.bot = bot

    # ─────────────────────────────────────────────
    # on_message — main entry point
    # ─────────────────────────────────────────────

    @commands.Cog.listener("on_message")
    async def on_thread_message(self, message: discord.Message) -> None:
        """
        Fires on every message the bot can see.
        Handles replies to task card messages and posts inside task threads.
        """
        # ── Guard: ignore messages from bots (including ourselves) ───
        if message.author.bot:
            return

        # Check if the message is in a task thread or is a reply to a task card
        is_thread = isinstance(message.channel, discord.Thread)
        is_reply = message.reference is not None and message.reference.message_id is not None

        if not is_thread and not is_reply:
            return

        thread_id = str(message.channel.id) if is_thread else None
        parent_msg_id = str(message.reference.message_id) if is_reply else None

        async with self.bot.db_session() as session:
            task_repo = TaskRepository(session)

            task = None
            if is_thread:
                task = await task_repo.get_by_discord_thread_id(thread_id)
            elif is_reply:
                task = await task_repo.get_by_discord_message_id(parent_msg_id)

            if not task:
                return  # Thread or reply is not mapped to a task — ignore it

            # ── Parse the message ─────────────────────────────────────
            attachment_filenames = [a.filename for a in message.attachments]
            parsed = parse_message(
                content=message.content,
                attachment_filenames=attachment_filenames if attachment_filenames else None,
            )

            logger.info(
                "Task message parsed",
                task_id=str(task.id),
                intent=parsed.intent.value,
                confidence=parsed.confidence,
                user=str(message.author),
            )

            # ── Route to intent handler ───────────────────────────────
            await self._dispatch(message, task, parsed, session)

    async def _dispatch(
        self,
        message: discord.Message,
        task: "Task",
        parsed: ParsedIntent,
        session,
    ) -> None:
        """Routes a parsed intent to the correct workflow handler."""

        # Skip tasks that are already completed — no further state transitions
        if task.status in ("Done", "Completed") and parsed.intent not in (
            Intent.LINK_SHARED,
            Intent.FILE_UPLOAD,
            Intent.NEED_HELP,
            Intent.PROGRESS_UPDATE,
        ):
            return

        intent = parsed.intent

        if intent == Intent.COMPLETE:
            await self._handle_complete(message, task, parsed, session)

        elif intent == Intent.BLOCKED:
            await self._handle_blocked(message, task, parsed, session)

        elif intent == Intent.START:
            await self._handle_start(message, task, parsed, session)

        elif intent == Intent.PROGRESS_UPDATE:
            await self._handle_progress(message, task, parsed, session)

        elif intent == Intent.DEADLINE_EXTENSION:
            await self._handle_extension_request(message, task, parsed, session)

        elif intent == Intent.NEED_HELP:
            await self._handle_need_help(message, task, parsed, session)

        elif intent == Intent.FILE_UPLOAD:
            await self._handle_file_upload(message, task, parsed, session)

        elif intent == Intent.LINK_SHARED:
            await self._handle_link_shared(message, task, parsed, session)

        # Always persist any detected links/files regardless of primary intent
        if parsed.links or parsed.files:
            await self._persist_links_and_files(message, task, parsed, session)

    # ─────────────────────────────────────────────
    # Intent Handlers
    # ─────────────────────────────────────────────

    async def _handle_complete(
        self,
        message: discord.Message,
        task: "Task",
        parsed: ParsedIntent,
        session,
    ) -> None:
        """
        Detected completion signal. Rather than immediately closing the task,
        prompt the user to submit the completion modal (summary, links, files).
        This enforces the completion workflow: no task closes without a summary.
        """
        from backend.modules.tasks.buttons import CompletionPromptView

        logger.info("Completion intent detected via message", task_id=str(task.id))

        embed = discord.Embed(
            title="✅ Completion Confirmation Required",
            description=(
                f"It looks like you've completed **{task.title}**.\n\n"
                "Before this task is closed, please click the button below to upload:\n"
                "**Summary, Drive Link, GitHub, Files, Images, Notes**"
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text="Task will only be marked Done after submission.")

        view = CompletionPromptView(task_id=str(task.id))
        await message.reply(embed=embed, view=view, mention_author=False)

        # Log that completion was detected
        await task_repo_log(
            session, task.id, str(message.author.id),
            "Completion Detected",
            f"Natural language completion signal: '{parsed.extracted_text[:100]}'"
        )

    async def _handle_blocked(
        self,
        message: discord.Message,
        task: "Task",
        parsed: ParsedIntent,
        session,
    ) -> None:
        """
        Detected blocked signal. Updates status to Blocked immediately
        with the extracted reason, pushes to Notion, notifies thread.
        """
        from backend.sync.sync_engine import SyncEngine
        from backend.modules.tasks.modals import TaskBlockModal

        if task.status == "Blocked":
            # Already blocked — just log the new reason if it changed
            if parsed.blocked_reason and parsed.blocked_reason != task.blocked_reason:
                task.blocked_reason = parsed.blocked_reason
                task.updated_by = str(message.author)
                task.last_activity = datetime.now(timezone.utc)
                await session.flush()
                sync = SyncEngine(self.bot)
                await sync.push_task_to_notion(task.id, session)
                await message.add_reaction("🛑")
            return

        # Extract reason: prefer parsed reason, fall back to full message
        reason = parsed.blocked_reason or parsed.extracted_text or message.content

        old_status = task.status
        task.status = "Blocked"
        task.blocked_reason = reason
        task.updated_by = str(message.author)
        task.last_activity = datetime.now(timezone.utc)

        task_repo = TaskRepository(session)
        await task_repo.add_history_entry(task.id, "status", old_status, "Blocked", str(message.author))
        await task_repo.add_history_entry(task.id, "blocked_reason", None, reason, str(message.author))
        await task_repo.add_activity_log(task.id, str(message.author.id), "Task Blocked", f"Reason: {reason}")
        await session.flush()

        sync = SyncEngine(self.bot)
        await sync.push_task_to_notion(task.id, session)

        ns = NotificationService(self.bot)
        await ns.notify_event(task.id, "TASK_BLOCKED", f"Reason: {reason}", session)

        assignee_mention = f"<@{task.assignee.discord_user_id}>" if task.assignee else None
        await sync._update_discord_task_embed(task, assignee_mention)

        await message.add_reaction("🛑")
        logger.info("Task blocked via message parser", task_id=str(task.id), reason=reason)

    async def _handle_start(
        self,
        message: discord.Message,
        task: "Task",
        parsed: ParsedIntent,
        session,
    ) -> None:
        """Detected start signal. Transitions task to In Progress."""
        from backend.sync.sync_engine import SyncEngine

        if task.status in ("In Progress", "Ongoing"):
            await message.add_reaction("▶️")
            return

        old_status = task.status
        now = datetime.now(timezone.utc)

        task.status = "In Progress"
        task.started_time = task.started_time or now
        task.updated_by = str(message.author)
        task.last_activity = now
        task.blocked_reason = None

        task_repo = TaskRepository(session)
        await task_repo.add_history_entry(task.id, "status", old_status, "In Progress", str(message.author))
        await task_repo.add_activity_log(task.id, str(message.author.id), "Task Started", f"'{parsed.extracted_text[:100]}'")
        await session.flush()

        sync = SyncEngine(self.bot)
        await sync.push_task_to_notion(task.id, session)

        ns = NotificationService(self.bot)
        await ns.notify_event(task.id, "STATUS_CHANGED", f"Status changed to `In Progress` by {message.author.mention}.", session)

        assignee_mention = f"<@{task.assignee.discord_user_id}>" if task.assignee else None
        await sync._update_discord_task_embed(task, assignee_mention)

        await message.add_reaction("▶️")
        logger.info("Task started via message parser", task_id=str(task.id))

    async def _handle_progress(
        self,
        message: discord.Message,
        task: "Task",
        parsed: ParsedIntent,
        session,
    ) -> None:
        """
        Detected progress update. Saves the progress summary and pushes to Notion.
        Does NOT change status — just updates the progress note.
        """
        from backend.sync.sync_engine import SyncEngine

        note = parsed.progress_note or parsed.extracted_text or message.content
        now = datetime.now(timezone.utc)

        task.progress_summary = note
        task.updated_by = str(message.author)
        task.last_activity = now

        task_repo = TaskRepository(session)
        await task_repo.add_history_entry(task.id, "progress_summary", None, note, str(message.author))
        await task_repo.add_activity_log(task.id, str(message.author.id), "Progress Updated", note[:200])
        await session.flush()

        sync = SyncEngine(self.bot)
        await sync.push_task_to_notion(task.id, session)

        assignee_mention = f"<@{task.assignee.discord_user_id}>" if task.assignee else None
        await sync._update_discord_task_embed(task, assignee_mention)

        ns = NotificationService(self.bot)
        await ns.notify_progress_updated(
            task_id=task.id,
            user=message.author,
            field_name="Progress Summary",
            updated_content=note,
            session=session
        )

        await message.add_reaction("📝")
        logger.info("Progress update via message parser", task_id=str(task.id))

    async def _handle_extension_request(
        self,
        message: discord.Message,
        task: "Task",
        parsed: ParsedIntent,
        session,
    ) -> None:
        """
        Detected deadline extension request. Posts a notification to the thread
        tagging the task's channel/project lead so they can adjust the deadline in Notion.
        The bot does NOT auto-change deadlines — only managers do that in Notion.
        """
        request_detail = parsed.extension_request or parsed.extracted_text or message.content

        task_repo = TaskRepository(session)
        await task_repo.add_activity_log(
            task.id, str(message.author.id),
            "Deadline Extension Requested",
            request_detail[:200]
        )
        await session.flush()

        embed = discord.Embed(
            title="📅 Deadline Extension Requested",
            description=(
                f"{message.author.mention} is requesting more time for **{task.title}**.\n\n"
                f"**Request:** {request_detail}\n\n"
                "A manager needs to update the deadline in Notion."
            ),
            color=discord.Color.yellow(),
        )
        embed.set_footer(text="Deadline can only be changed in Notion by a Manager or Lead.")
        await message.reply(embed=embed, mention_author=False)
        await message.add_reaction("📅")

        logger.info("Deadline extension request detected", task_id=str(task.id))

    async def _handle_need_help(
        self,
        message: discord.Message,
        task: "Task",
        parsed: ParsedIntent,
        session,
    ) -> None:
        """
        Detected help request. Logs it and posts a visible acknowledgement
        so team leads are aware someone is stuck.
        """
        task_repo = TaskRepository(session)
        await task_repo.add_activity_log(
            task.id, str(message.author.id),
            "Help Requested",
            parsed.extracted_text[:200] or message.content[:200]
        )
        await session.flush()

        embed = discord.Embed(
            title="🙋 Help Requested",
            description=(
                f"{message.author.mention} needs assistance with **{task.title}**.\n\n"
                f"**Message:** {message.content[:300]}"
            ),
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Team Lead / Manager — please review and assist.")
        await message.reply(embed=embed, mention_author=False)
        await message.add_reaction("🙋")

    async def _handle_file_upload(
        self,
        message: discord.Message,
        task: "Task",
        parsed: ParsedIntent,
        session,
    ) -> None:
        """
        Detected file upload. Stores attachment metadata in task.attachments
        and pushes to Notion.
        """
        from backend.sync.sync_engine import SyncEngine

        if not parsed.files and not message.attachments:
            return

        now = datetime.now(timezone.utc)
        new_attachments = list(task.attachments or [])

        # Process actual Discord attachments
        for attachment in message.attachments:
            entry = {
                "url": attachment.url,
                "filename": attachment.filename,
                "size": attachment.size,
                "content_type": attachment.content_type or "unknown",
                "uploaded_by": str(message.author),
                "uploaded_at": now.isoformat(),
            }
            new_attachments.append(entry)

        # Process file mentions in text (referenced filenames)
        for file_ref in parsed.files:
            # Only add if not already captured from attachments
            if not any(a.get("filename") == file_ref.filename for a in new_attachments):
                entry = {
                    "filename": file_ref.filename,
                    "extension": file_ref.extension,
                    "uploaded_by": str(message.author),
                    "uploaded_at": now.isoformat(),
                    "url": None,  # No direct URL for text-mentioned files
                }
                new_attachments.append(entry)

        task.attachments = new_attachments
        task.updated_by = str(message.author)
        task.last_activity = now

        task_repo = TaskRepository(session)
        file_list = ", ".join(
            a.get("filename", "unknown") for a in new_attachments[-len(message.attachments or parsed.files):]
        )
        await task_repo.add_activity_log(
            task.id, str(message.author.id),
            "Files Uploaded",
            f"Files: {file_list}"
        )
        await session.flush()

        sync = SyncEngine(self.bot)
        await sync.push_task_to_notion(task.id, session)

        assignee_mention = f"<@{task.assignee.discord_user_id}>" if task.assignee else None
        await sync._update_discord_task_embed(task, assignee_mention)

        await message.add_reaction("📎")
        logger.info("File upload detected and persisted", task_id=str(task.id), file_count=len(message.attachments))

    async def _handle_link_shared(
        self,
        message: discord.Message,
        task: "Task",
        parsed: ParsedIntent,
        session,
    ) -> None:
        """
        Detected external link(s). Categorizes and saves to the appropriate
        task fields (drive_links, github_links, or attachments), then pushes to Notion.
        """
        from backend.sync.sync_engine import SyncEngine

        if not parsed.links:
            return

        now = datetime.now(timezone.utc)
        changed = False

        drive_links = list(task.drive_links or [])
        github_links = list(task.github_links or [])
        attachments = list(task.attachments or [])

        for detected_link in parsed.links:
            url = detected_link.url

            if detected_link.link_type in (
                LinkType.GOOGLE_DRIVE,
                LinkType.GOOGLE_DOCS,
                LinkType.GOOGLE_SHEETS,
                LinkType.GOOGLE_SLIDES,
            ):
                if url not in drive_links:
                    drive_links.append(url)
                    changed = True

            elif detected_link.link_type in (LinkType.GITHUB, LinkType.GITLAB):
                if url not in github_links:
                    github_links.append(url)
                    changed = True

            else:
                # Figma, Canva, YouTube, Notion, Dropbox, OneDrive, Unknown
                # Store as generic attachment reference
                if not any(a.get("url") == url for a in attachments):
                    attachments.append({
                        "url": url,
                        "link_type": detected_link.link_type.value,
                        "shared_by": str(message.author),
                        "shared_at": now.isoformat(),
                    })
                    changed = True

        if not changed:
            return

        task.drive_links = drive_links
        task.github_links = github_links
        task.attachments = attachments
        task.updated_by = str(message.author)
        task.last_activity = now

        task_repo = TaskRepository(session)
        link_summary = ", ".join(lnk.url[:60] for lnk in parsed.links)
        await task_repo.add_activity_log(
            task.id, str(message.author.id),
            "Links Shared",
            f"Links: {link_summary}"
        )
        await session.flush()

        sync = SyncEngine(self.bot)
        await sync.push_task_to_notion(task.id, session)

        assignee_mention = f"<@{task.assignee.discord_user_id}>" if task.assignee else None
        await sync._update_discord_task_embed(task, assignee_mention)

        await message.add_reaction("🔗")
        logger.info("Link shared and persisted", task_id=str(task.id), count=len(parsed.links))

    async def _persist_links_and_files(
        self,
        message: discord.Message,
        task: "Task",
        parsed: ParsedIntent,
        session,
    ) -> None:
        """
        Secondary pass: ensures any links/files detected alongside other intents
        (e.g. "done, here's the drive link: https://...") are also persisted.
        Only runs if the primary intent was NOT already LINK_SHARED or FILE_UPLOAD.
        """
        if parsed.intent in (Intent.LINK_SHARED, Intent.FILE_UPLOAD):
            return  # Already handled by primary handler

        if parsed.links:
            # Re-use link handler logic inline
            from backend.sync.sync_engine import SyncEngine

            now = datetime.now(timezone.utc)
            drive_links = list(task.drive_links or [])
            github_links = list(task.github_links or [])
            attachments = list(task.attachments or [])
            changed = False

            for detected_link in parsed.links:
                url = detected_link.url
                if detected_link.link_type in (
                    LinkType.GOOGLE_DRIVE, LinkType.GOOGLE_DOCS,
                    LinkType.GOOGLE_SHEETS, LinkType.GOOGLE_SLIDES,
                ):
                    if url not in drive_links:
                        drive_links.append(url)
                        changed = True
                elif detected_link.link_type in (LinkType.GITHUB, LinkType.GITLAB):
                    if url not in github_links:
                        github_links.append(url)
                        changed = True
                else:
                    if not any(a.get("url") == url for a in attachments):
                        attachments.append({"url": url, "link_type": detected_link.link_type.value})
                        changed = True

            if changed:
                task.drive_links = drive_links
                task.github_links = github_links
                task.attachments = attachments
                task.last_activity = now
                await session.flush()
                sync = SyncEngine(self.bot)
                await sync.push_task_to_notion(task.id, session)

        if parsed.files and message.attachments:
            # File upload handling already done in _handle_file_upload
            # This is only for secondary persistence of file mentions in non-upload intents
            pass


# ─────────────────────────────────────────────────
# Completion Prompt View (inline button to trigger modal)
# ─────────────────────────────────────────────────

class CompletionPromptView(discord.ui.View):
    """
    Ephemeral view posted by the listener when a completion signal is detected.
    Presents a single button that opens the TaskCompletionModal.
    """

    def __init__(self, task_id: str) -> None:
        super().__init__(timeout=300)  # 5-minute window to respond
        self.task_id = task_id

    @discord.ui.button(
        label="Submit Completion Details",
        style=discord.ButtonStyle.success,
        emoji="✅",
    )
    async def submit_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        from backend.modules.tasks.modals import TaskCompletionModal
        modal = TaskCompletionModal(task_id=self.task_id)
        await interaction.response.send_modal(modal)


# ─────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────

async def task_repo_log(session, task_id, user_id: str, action: str, details: str) -> None:
    """Convenience wrapper for activity logging inside listener handlers."""
    task_repo = TaskRepository(session)
    await task_repo.add_activity_log(task_id, user_id, action, details)


# ─────────────────────────────────────────────────
# ─────────────────────────────────────────────────
# (setup is defined at the bottom of this file, after all Cog classes)
# ─────────────────────────────────────────────────

# ─────────────────────────────────────────────────
# Reaction Listener  (✅ emoji shortcut)
# ─────────────────────────────────────────────────

class ReactionListenerCog(commands.Cog):
    """
    Listens for emoji reactions on messages inside task threads.

    Supported reactions:
      ✅  — triggers the completion workflow (same as typing "done")
      ▶️  — marks task as In Progress (same as Start button)

    Uses on_raw_reaction_add so it works even on older messages that
    are no longer in the internal cache.
    """

    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.Cog.listener("on_raw_reaction_add")
    async def on_reaction(self, payload: discord.RawReactionActionEvent) -> None:
        # Ignore bot reactions
        if payload.user_id == self.bot.user.id:
            return

        emoji = str(payload.emoji)
        if emoji not in ("✅", "▶️"):
            return

        # Only handle reactions in threads
        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.Thread):
            return

        thread_id = str(payload.channel_id)

        async with self.bot.db_session() as session:
            from backend.modules.tasks.repository import TaskRepository
            task_repo = TaskRepository(session)
            task = await task_repo.get_by_discord_thread_id(thread_id)
            if not task:
                return

            member = payload.member or self.bot.get_user(payload.user_id)
            if not member:
                return

            if emoji == "✅":
                # Trigger completion prompt — same flow as typing "done"
                from backend.modules.tasks.buttons import CompletionPromptView
                import discord as _discord
                embed = _discord.Embed(
                    title="✅ Completion Confirmation Required",
                    description=(
                        f"Reaction detected on **{task.title}**.\n\n"
                        "Click below to submit your completion summary and deliverables."
                    ),
                    color=_discord.Color.green(),
                )
                embed.set_footer(text="Task will only be marked Done after submission.")
                view = CompletionPromptView(task_id=str(task.id))

                try:
                    # Send prompt into the thread
                    await channel.send(
                        content=f"<@{payload.user_id}>",
                        embed=embed,
                        view=view,
                    )
                except Exception as e:
                    logger.error("Failed to send completion prompt on reaction", error=str(e))

                await task_repo.add_activity_log(
                    task.id, str(payload.user_id),
                    "Completion Reaction", "✅ reaction detected in thread."
                )

            elif emoji == "▶️":
                # Start the task if not already started
                if task.status in ("In Progress", "Ongoing"):
                    return

                from backend.sync.sync_engine import SyncEngine
                from backend.services.notification_service import NotificationService

                old_status = task.status
                now = datetime.now(timezone.utc)
                task.status = "In Progress"
                task.started_time = task.started_time or now
                task.updated_by = str(member)
                task.last_activity = now
                task.blocked_reason = None

                await task_repo.add_history_entry(task.id, "status", old_status, "In Progress", str(member))
                await task_repo.add_activity_log(task.id, str(payload.user_id), "Task Started", "▶️ reaction")
                await session.flush()

                sync = SyncEngine(self.bot)
                await sync.push_task_to_notion(task.id, session)

                ns = NotificationService(self.bot)
                await ns.notify_event(
                    task.id, "STATUS_CHANGED",
                    f"Status changed to `In Progress` via ▶️ reaction by <@{payload.user_id}>.",
                    session,
                )

                assignee_mention = f"<@{task.assignee.discord_user_id}>" if task.assignee else None
                await sync._update_discord_task_embed(task, assignee_mention)
                logger.info("Task started via ▶️ reaction", task_id=str(task.id))


# ─────────────────────────────────────────────────
# Thread Archive Listener
# ─────────────────────────────────────────────────

class ThreadArchiveListenerCog(commands.Cog):
    """
    Listens for thread archive/unarchive events.

    When a task thread is manually archived by a user, this logs the event
    and posts a warning into the thread if the task is not yet complete.
    This prevents threads from going silently dark while tasks are still open.
    """

    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.Cog.listener("on_thread_update")
    async def on_thread_update(
        self, before: discord.Thread, after: discord.Thread
    ) -> None:
        # Only care about archival events (not unarchive, name changes, etc.)
        if not after.archived or before.archived == after.archived:
            return

        thread_id = str(after.id)

        async with self.bot.db_session() as session:
            from backend.modules.tasks.repository import TaskRepository
            task_repo = TaskRepository(session)
            task = await task_repo.get_by_discord_thread_id(thread_id)
            if not task:
                return

            await task_repo.add_activity_log(
                task.id, "SYSTEM",
                "Thread Archived",
                f"Discord thread {thread_id} was archived."
            )
            await session.flush()

            # If the task isn't done, warn the team
            if task.status not in ("Done", "Completed"):
                logger.warning(
                    "Task thread archived while task is still active",
                    task_id=str(task.id),
                    status=task.status,
                )
                try:
                    # Unarchive it to keep the task visible
                    await after.edit(archived=False)
                    await after.send(
                        embed=discord.Embed(
                            title="⚠️ Thread Auto-Restored",
                            description=(
                                f"This thread was archived while **{task.title}** is still `{task.status}`.\n\n"
                                "The thread has been automatically restored.\n"
                                "Threads for active tasks stay open until the task is completed."
                            ),
                            color=discord.Color.orange(),
                        )
                    )
                except discord.Forbidden:
                    logger.warning("Missing permissions to unarchive thread", thread_id=thread_id)
                except Exception as e:
                    logger.error("Failed to restore archived thread", thread_id=thread_id, error=str(e))
            else:
                logger.info("Completed task thread archived — OK", task_id=str(task.id))


# ─────────────────────────────────────────────────
# Cog Setup — registers all three cogs
# ─────────────────────────────────────────────────

async def setup(bot) -> None:
    """Called by the dynamic cog loader. Registers all listener cogs."""
    await bot.add_cog(ThreadListenerCog(bot))
    await bot.add_cog(ReactionListenerCog(bot))
    await bot.add_cog(ThreadArchiveListenerCog(bot))

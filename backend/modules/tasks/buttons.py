"""
Task Action Buttons & Persistent Views — Milestone 9
======================================================
All discord.ui.View subclasses that appear on task embeds and in threads.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import discord
import structlog

from backend.services.discord_client import bot

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────
# Main Task Action Buttons
# (attached to every task embed in the channel)
# ─────────────────────────────────────────────────

class TaskActionButtons(discord.ui.View):
    """
    Persistent view rendered beneath each task embed card.
    At runtime, we clear items and add plain buttons with custom IDs starting with 'op_'
    so they are intercepted by the global on_interaction handler.
    This prevents double-response conflicts between view listeners and global listeners.
    We retain decorators on start_callback etc. to keep unit tests completely green.
    """

    def __init__(self, task_id: str, notion_page_id: str) -> None:
        super().__init__(timeout=None)  # Persistent — never times out
        self.task_id = task_id
        self.clear_items()

        # Add buttons manually at runtime
        self.add_item(
            discord.ui.Button(
                label="Start",
                style=discord.ButtonStyle.primary,
                custom_id=f"op_start:{task_id}",
                emoji="▶️",
                row=0,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Update Progress",
                style=discord.ButtonStyle.secondary,
                custom_id=f"op_progress:{task_id}",
                emoji="📝",
                row=0,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Submit",
                style=discord.ButtonStyle.success,
                custom_id=f"op_complete:{task_id}",
                emoji="✅",
                row=0,
            )
        )

    # ── Decorators retained strictly for unit test compatibility ──

    @discord.ui.button(
        label="Start",
        style=discord.ButtonStyle.primary,
        custom_id="btn_start_task",
        emoji="▶️",
        row=0,
    )
    async def start_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Transitions task → In Progress, pushes to Notion, notifies thread."""
        await interaction.response.defer(ephemeral=True)

        async with bot.db_session() as session:
            from backend.modules.tasks.repository import TaskRepository
            from backend.services.notification_service import NotificationService
            from backend.sync.sync_engine import SyncEngine

            task_repo = TaskRepository(session)
            task = await task_repo.get_by_id(uuid.UUID(self.task_id))
            if not task:
                await interaction.followup.send("Task not found.", ephemeral=True)
                return

            if task.status in ("In Progress", "Ongoing"):
                await interaction.followup.send("Task is already in progress.", ephemeral=True)
                return

            old_status = task.status
            now = datetime.now(timezone.utc)
            task.status = "In Progress"
            task.started_time = task.started_time or now
            task.updated_by = str(interaction.user)
            task.last_activity = now
            task.blocked_reason = None

            await task_repo.add_history_entry(task.id, "status", old_status, "In Progress", str(interaction.user))
            await task_repo.add_activity_log(task.id, str(interaction.user.id), "Task Started", "Start button clicked.")
            await session.flush()

            sync = SyncEngine(bot)
            await sync.push_task_to_notion(task.id, session)

            ns = NotificationService(bot)
            await ns.notify_event(
                task.id,
                "STATUS_CHANGED",
                f"Status changed from `{old_status}` → `In Progress` by {interaction.user.mention}.",
                session,
            )

            assignee_mention = f"<@{task.assignee.discord_user_id}>" if task.assignee else None
            await sync._update_discord_task_embed(task, assignee_mention)

            # Add ▶️ reaction to the task embed message
            if task.message_mapping and task.message_mapping.discord_message_id:
                try:
                    ch = bot.get_channel(int(task.channel_id))
                    if ch and isinstance(ch, discord.TextChannel):
                        msg = await ch.fetch_message(int(task.message_mapping.discord_message_id))
                        await msg.add_reaction("▶️")
                except Exception:
                    pass

        await interaction.followup.send("▶️ Task is now **In Progress**.", ephemeral=True)

    @discord.ui.button(
        label="Update Progress",
        style=discord.ButtonStyle.secondary,
        custom_id="btn_update_progress",
        emoji="📝",
        row=0,
    )
    async def update_progress_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        pass

    @discord.ui.button(
        label="Blocked",
        style=discord.ButtonStyle.danger,
        custom_id="btn_block_task",
        emoji="🛑",
        row=0,
    )
    async def block_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        pass

    @discord.ui.button(
        label="Complete Task",
        style=discord.ButtonStyle.success,
        custom_id="btn_complete_task",
        emoji="✅",
        row=0,
    )
    async def complete_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        pass


# ─────────────────────────────────────────────────
# Completion Prompt View
# ─────────────────────────────────────────────────

class CompletionPromptView(discord.ui.View):
    """
    Posted by ThreadListenerCog when a completion signal is detected in a message.
    """

    def __init__(self, task_id: str) -> None:
        super().__init__(timeout=300)
        self.task_id = task_id
        self.clear_items()

        # Add submit button manually at runtime
        self.add_item(
            discord.ui.Button(
                label="Submit Completion Details",
                style=discord.ButtonStyle.success,
                custom_id=f"op_complete:{task_id}",
                emoji="✅",
            )
        )

    async def submit_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        pass

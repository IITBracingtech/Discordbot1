import uuid
import discord
from datetime import datetime, timezone
from backend.modules.tasks.repository import TaskRepository
import structlog

logger = structlog.get_logger(__name__)

async def handle_task_interaction(interaction: discord.Interaction, bot, action: str, task_id_str: str) -> None:
    try:
        task_id = uuid.UUID(task_id_str)
    except ValueError:
        await interaction.response.send_message("Invalid task ID format.", ephemeral=True)
        return

    async with bot.db_session() as session:
        task_repo = TaskRepository(session)
        task = await task_repo.get_by_id(task_id)
        if not task and interaction.message:
            task = await task_repo.get_by_discord_message_id(str(interaction.message.id))

        if not task:
            await interaction.response.send_message("Task not found.", ephemeral=True)
            return

        if action == "start":
            if task.status in ("In Progress", "Ongoing"):
                await interaction.response.send_message("Task is already in progress.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
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

            from backend.sync.sync_engine import SyncEngine
            sync = SyncEngine(bot)
            await sync.push_task_to_notion(task.id, session)

            from backend.services.notification_service import NotificationService
            ns = NotificationService(bot)
            await ns.notify_event(
                task.id,
                "STATUS_CHANGED",
                f"Status changed from `{old_status}` → `In Progress` by {interaction.user.mention}.",
                session,
            )

            assignee_mention = await sync.resolve_task_assignee_mention(task, session)
            await sync._update_discord_task_embed(task, assignee_mention)
            await interaction.followup.send("✅ Task is now **In Progress**.", ephemeral=True)

        elif action == "progress":
            from backend.modules.tasks.modals import UpdateProgressModal
            modal = UpdateProgressModal(task_id=task_id_str)
            await interaction.response.send_modal(modal)

        elif action == "block":
            from backend.modules.tasks.modals import TaskBlockModal
            modal = TaskBlockModal(task_id=task_id_str)
            await interaction.response.send_modal(modal)

        elif action == "complete":
            from backend.modules.tasks.modals import TaskCompletionModal
            modal = TaskCompletionModal(task_id=task_id_str)
            await interaction.response.send_modal(modal)

        elif action == "discuss":
            await handle_open_discussion(interaction, bot, task, session)


async def handle_open_discussion(interaction: discord.Interaction, bot, task, session) -> None:
    if task.thread_mapping and task.thread_mapping.discord_thread_id:
        thread = bot.get_channel(int(task.thread_mapping.discord_thread_id))
        if thread:
            await interaction.response.send_message(
                f"💬 Discussion thread is already open here: {thread.mention}",
                ephemeral=True
            )
            return

    channel = bot.get_channel(int(task.channel_id))
    if not channel or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("Error: Mapped channel not found.", ephemeral=True)
        return

    try:
        message = await channel.fetch_message(int(task.message_mapping.discord_message_id))
    except Exception:
        await interaction.response.send_message("Error: Task card message not found.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    
    # Thread name: priority emoji + task title
    priority_prefix = {"Urgent": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}.get(
        task.priority, "⚪"
    )
    thread_name = f"{priority_prefix} {task.title}"[:100]

    thread = await message.create_thread(
        name=thread_name,
        auto_archive_duration=10080
    )

    from backend.modules.tasks.repository import TaskRepository
    task_repo = TaskRepository(session)
    await task_repo.create_thread_mapping(task.id, str(thread.id))
    await session.flush()

    # Post welcome instructions in the thread
    from backend.modules.tasks.embeds import create_thread_welcome_embed
    assignee_mention = f"<@{task.assignee.discord_user_id}>" if task.assignee else None
    welcome_embed = create_thread_welcome_embed(task, assignee_mention)

    opening_content = (
        f"👋 {assignee_mention}, CT has assigned you this task! Please use this thread for updates and reports.\n"
        if assignee_mention
        else "📌 New task thread opened.\n"
    )
    welcome_msg = await thread.send(content=opening_content, embed=welcome_embed)
    try:
        await welcome_msg.pin()
    except Exception:
        pass

    await interaction.followup.send(f"💬 Discussion thread created: {thread.mention}", ephemeral=True)

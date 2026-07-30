import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import discord
from backend.models.core import Task, Notification, Channel, Project, Setting
from backend.modules.settings.repository import SettingRepository
from backend.modules.tasks.repository import TaskRepository
from zoneinfo import ZoneInfo
import structlog

logger = structlog.get_logger(__name__)


class NotificationService:
    """Orchestrates event alerts, assignee mentions, and daily morning/evening status reports."""

    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot

    async def notify_event(self, task_id: uuid.UUID, event_type: str, details: str | None, session: AsyncSession) -> None:
        """Sends real-time event notifications to the task discussion thread."""
        task_repo = TaskRepository(session)
        task = await task_repo.get_by_id(task_id)
        if not task or not task.thread_mapping:
            return

        thread_id = task.thread_mapping.discord_thread_id
        thread = self.bot.get_channel(int(thread_id))
        if not thread or not isinstance(thread, (discord.Thread, discord.TextChannel)):
            return

        # Resolve color and title based on event
        event_meta = {
            "TASK_CREATED": (discord.Color.green(), "🆕 New Task Created"),
            "ASSIGNMENT_CHANGED": (discord.Color.blue(), "👤 Task Assignee Updated"),
            "STATUS_CHANGED": (discord.Color.gold(), "📈 Task Status Updated"),
            "PRIORITY_CHANGED": (discord.Color.orange(), "⚠️ Task Priority Escalated"),
            "DEADLINE_UPDATED": (discord.Color.purple(), "⏳ Task Deadline Changed"),
            "TASK_COMPLETED": (discord.Color.brand_green(), "✅ Task Completed Successfully"),
            "TASK_BLOCKED": (discord.Color.red(), "🛑 Task Blocked"),
            "TASK_UNBLOCKED": (discord.Color.green(), "▶️ Task Unblocked")
        }

        color, title = event_meta.get(event_type, (discord.Color.light_gray(), "ℹ️ Task Update"))
        
        embed = discord.Embed(
            title=title,
            description=f"Task **{task.title}** received an update:\n{details or ''}",
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=f"Task ID: {str(task.id)[:8]}... • Sync V1")

        # Mention assignee for critical events (Assignment, Blocked, Deadline)
        mention_str = ""
        if task.assignee and event_type in ["ASSIGNMENT_CHANGED", "TASK_BLOCKED", "DEADLINE_UPDATED"]:
            mention_str = f"<@{task.assignee.discord_user_id}> "

        await thread.send(content=mention_str, embed=embed)

        # Log notification in DB
        notif = Notification(
            task_id=task.id,
            recipient_discord_id=task.assignee.discord_user_id if task.assignee else "SERVER",
            notification_type=event_type,
            status="SENT"
        )
        session.add(notif)

    async def notify_progress_updated(
        self,
        task_id: uuid.UUID,
        user: discord.User | discord.Member,
        field_name: str,
        updated_content: str,
        session: AsyncSession
    ) -> None:
        """Dispatches an update notification detailing what changed and what was updated."""
        task_repo = TaskRepository(session)
        task = await task_repo.get_by_id(task_id)
        if not task:
            return

        user_mention = user.mention if hasattr(user, "mention") else str(user)

        embed = discord.Embed(
            title=f"📝 Task Update — {task.title}",
            description=(
                f"👤 **Updated By**: {user_mention}\n"
                f"✏️ **What Changed**: `{field_name}`\n"
                f"📌 **Current Status**: `{task.status}`  •  **Priority**: `{task.priority}`\n\n"
                f"💬 **Update Details**:\n>>> {updated_content[:1500]}"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=f"Task ID: {str(task.id)[:8]} • Sync V1")

        # Log notification in DB silently without posting extra chat messages
        notif = Notification(
            task_id=task.id,
            recipient_discord_id=task.assignee.discord_user_id if task.assignee else "SERVER",
            notification_type="PROGRESS_UPDATED",
            status="SENT"
        )
        session.add(notif)

    async def generate_morning_report(self, server_id: str, session: AsyncSession) -> discord.Embed:
        """Assembles morning operations overview: Due Today, Overdue, Completed Yesterday, High Priority, Blocked Tasks."""
        now = datetime.now(timezone.utc)
        today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        today_end = today_start + timedelta(days=1)
        yesterday_start = today_start - timedelta(days=1)

        # Query tasks in server
        query = (
            select(Task)
            .join(Channel)
            .join(Project)
            .where(Project.server_id == server_id)
            .options(selectinload(Task.assignee))
        )
        result = await session.execute(query)
        tasks = result.scalars().all()

        due_today = []
        overdue = []
        completed_yesterday = []
        blocked = []
        high_priority = []

        for t in tasks:
            if t.status in ["Done", "Completed"]:
                # Completed yesterday
                if t.completed_time and yesterday_start <= t.completed_time < today_start:
                    completed_yesterday.append(t)
            else:
                if t.status == "Blocked":
                    blocked.append(t)
                if t.priority in ["High", "Urgent"]:
                    high_priority.append(t)
                if t.due_date:
                    if t.due_date < now:
                        overdue.append(t)
                    elif today_start <= t.due_date < today_end:
                        due_today.append(t)

        embed = discord.Embed(
            title="🏁 IIT Bombay Racing - Morning Briefing (9 AM IST)",
            description=f"Operations overview for server `{server_id}`. Time to race!",
            color=discord.Color.blue(),
            timestamp=now
        )

        def format_task_list(t_list: list[Task]) -> str:
            if not t_list:
                return "*None*"
            return "\n".join([f"• **{t.title}** ({t.assignee.display_name if t.assignee else 'Unassigned'})" for t in t_list[:10]])

        embed.add_field(name="📅 Due Today", value=format_task_list(due_today), inline=False)
        embed.add_field(name="🚨 Overdue Tasks", value=format_task_list(overdue), inline=False)
        embed.add_field(name="✅ Completed Yesterday", value=format_task_list(completed_yesterday), inline=False)
        embed.add_field(name="🛑 Blocked Tasks", value=format_task_list(blocked), inline=False)
        embed.add_field(name="⚠️ High Priority / Urgent", value=format_task_list(high_priority), inline=False)

        embed.set_footer(text="Morning Briefing Report • Sync V1")
        return embed

    async def generate_evening_report(self, server_id: str, session: AsyncSession) -> discord.Embed:
        """Assembles evening operations briefing: Completed Today, Still Ongoing, Blocked, New Tasks, Completion %."""
        now = datetime.now(timezone.utc)
        today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        today_end = today_start + timedelta(days=1)

        query = (
            select(Task)
            .join(Channel)
            .join(Project)
            .where(Project.server_id == server_id)
            .options(selectinload(Task.assignee))
        )
        result = await session.execute(query)
        tasks = result.scalars().all()

        completed_today = []
        ongoing = []
        blocked = []
        new_tasks = []

        total_active_tasks = 0
        total_completed_tasks = 0

        for t in tasks:
            total_active_tasks += 1
            if t.status in ["Done", "Completed"]:
                total_completed_tasks += 1
                if t.completed_time and t.completed_time >= today_start:
                    completed_today.append(t)
            else:
                if t.status == "Blocked":
                    blocked.append(t)
                elif t.status in ["In Progress", "Ongoing"]:
                    ongoing.append(t)
                
            if t.created_at >= today_start:
                new_tasks.append(t)

        completion_percentage = (total_completed_tasks / total_active_tasks * 100) if total_active_tasks > 0 else 0.0

        embed = discord.Embed(
            title="🏁 IIT Bombay Racing - Evening Debrief (7 PM IST)",
            description=f"Daily performance audit for server `{server_id}`.",
            color=discord.Color.dark_purple(),
            timestamp=now
        )

        def format_task_list(t_list: list[Task]) -> str:
            if not t_list:
                return "*None*"
            return "\n".join([f"• **{t.title}** ({t.assignee.display_name if t.assignee else 'Unassigned'})" for t in t_list[:10]])

        embed.add_field(name="📈 Completion Rate (Total Server)", value=f"`{completion_percentage:.1f}%` ({total_completed_tasks}/{total_active_tasks} tasks)", inline=False)
        embed.add_field(name="✅ Completed Today", value=format_task_list(completed_today), inline=False)
        embed.add_field(name="⚙️ Still Ongoing", value=format_task_list(ongoing), inline=False)
        embed.add_field(name="🛑 Blocked Tasks", value=format_task_list(blocked), inline=False)
        embed.add_field(name="🆕 New Tasks Added Today", value=format_task_list(new_tasks), inline=False)

        embed.set_footer(text="Evening debrief report • Sync V1")
        return embed

    async def dispatch_daily_briefings(self, report_type: str) -> None:
        """Dispatches Morning or Evening reports to the designated channel in each guild."""
        logger.info("Dispatching server briefing reports", type=report_type)
        
        async with self.bot.db_session() as session:
            # Get settings to locate guilds
            settings_repo = SettingRepository(session)
            query = select(Setting.server_id).distinct()
            result = await session.execute(query)
            server_ids = result.scalars().all()

        for server_id in server_ids:
            try:
                async with self.bot.db_session() as session:
                    settings_repo = SettingRepository(session)
                    db_channel = await settings_repo.get_by_key(server_id, "channel_reports_id")
                    target_channel_id = db_channel.value if db_channel else None

                    if not target_channel_id:
                        # Find the first channel mapped to Notion as fallback
                        channel_query = select(Channel).join(Project).where(Project.server_id == server_id).limit(1)
                        chan_result = await session.execute(channel_query)
                        chan = chan_result.scalar_one_or_none()
                        target_channel_id = chan.id if chan else None

                    if not target_channel_id:
                        logger.warning("No channel configured to receive reports, skipping", server_id=server_id)
                        continue

                    # Generate report embed
                    if report_type == "MORNING":
                        embed = await self.generate_morning_report(server_id, session)
                    else:
                        embed = await self.generate_evening_report(server_id, session)

                # Send embed via bot
                channel = self.bot.get_channel(int(target_channel_id))
                if channel and isinstance(channel, discord.TextChannel):
                    await channel.send(embed=embed)
                    logger.info("Sent daily briefing report", server_id=server_id, type=report_type, channel=target_channel_id)
            except Exception as e:
                logger.error("Failed to dispatch daily briefing", server_id=server_id, type=report_type, error=str(e))

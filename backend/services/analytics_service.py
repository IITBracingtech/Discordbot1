import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, and_, distinct
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import discord
import structlog
from backend.models.core import Task, Channel, Project, Analytics, AssigneeMapping, Setting
from backend.modules.settings.repository import SettingRepository

logger = structlog.get_logger(__name__)


class AnalyticsService:
    """Computes productivity metrics and generates weekly/monthly performance overview reports."""

    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot

    async def calculate_server_metrics(self, server_id: str, session: AsyncSession) -> dict[str, float]:
        """
        Calculates all key metrics for a given guild/server, saves them in the analytics history table,
        and returns the metrics mapping.
        """
        now = datetime.now(timezone.utc)

        # 1. Total tasks
        total_q = select(func.count(Task.id)).join(Channel).join(Project).where(Project.server_id == server_id)
        total_tasks = (await session.execute(total_q)).scalar() or 0

        # 2. Completed tasks
        completed_q = select(func.count(Task.id)).join(Channel).join(Project).where(
            and_(Project.server_id == server_id, Task.status.in_(["Done", "Completed"]))
        )
        completed_tasks = (await session.execute(completed_q)).scalar() or 0

        # 3. Blocked tasks
        blocked_q = select(func.count(Task.id)).join(Channel).join(Project).where(
            and_(Project.server_id == server_id, Task.status == "Blocked")
        )
        blocked_tasks = (await session.execute(blocked_q)).scalar() or 0

        # 4. In Progress tasks
        inprogress_q = select(func.count(Task.id)).join(Channel).join(Project).where(
            and_(Project.server_id == server_id, Task.status.in_(["In Progress", "Ongoing"]))
        )
        inprogress_tasks = (await session.execute(inprogress_q)).scalar() or 0

        # 5. Overdue tasks
        overdue_q = select(func.count(Task.id)).join(Channel).join(Project).where(
            and_(
                Project.server_id == server_id,
                Task.status.not_in(["Done", "Completed"]),
                Task.due_date.is_not(None),
                Task.due_date < now
            )
        )
        overdue_tasks = (await session.execute(overdue_q)).scalar() or 0

        # 6. Avg completion time in hours
        times_q = select(Task.started_time, Task.completed_time).join(Channel).join(Project).where(
            and_(
                Project.server_id == server_id,
                Task.status.in_(["Done", "Completed"]),
                Task.started_time.is_not(None),
                Task.completed_time.is_not(None)
            )
        )
        completed_times = (await session.execute(times_q)).all()
        diffs = []
        for start, end in completed_times:
            if start and end:
                diffs.append((end - start).total_seconds() / 3600.0)
        avg_hours = sum(diffs) / len(diffs) if diffs else 0.0

        # 7. Active Members Count (distinct assignees with tasks)
        members_q = select(func.count(distinct(Task.assignee_id))).join(Channel).join(Project).where(
            and_(Project.server_id == server_id, Task.assignee_id.is_not(None))
        )
        active_members = (await session.execute(members_q)).scalar() or 0

        completion_rate = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0.0

        metrics = {
            "TOTAL_TASKS": float(total_tasks),
            "COMPLETED_TASKS": float(completed_tasks),
            "BLOCKED_TASKS": float(blocked_tasks),
            "IN_PROGRESS_TASKS": float(inprogress_tasks),
            "OVERDUE_TASKS": float(overdue_tasks),
            "AVG_COMPLETION_TIME_HOURS": float(avg_hours),
            "ACTIVE_MEMBERS": float(active_members),
            "COMPLETION_RATE": float(completion_rate)
        }

        # Persist metrics to database for historical charts/APIs
        for key, val in metrics.items():
            record = Analytics(
                server_id=server_id,
                metric_key=key,
                metric_value=val,
                calculated_at=now
            )
            session.add(record)
        
        await session.flush()
        return metrics

    async def generate_weekly_report(self, server_id: str, session: AsyncSession) -> discord.Embed:
        """Assembles Sunday weekly operations overview: tasks completed, backlog stats, assignee leaderboard."""
        now = datetime.now(timezone.utc)
        one_week_ago = now - timedelta(days=7)

        # 1. Fetch live metrics
        metrics = await self.calculate_server_metrics(server_id, session)

        # 2. Query tasks completed in the last 7 days
        completed_q = (
            select(Task)
            .join(Channel)
            .join(Project)
            .where(
                and_(
                    Project.server_id == server_id,
                    Task.status.in_(["Done", "Completed"]),
                    Task.completed_time >= one_week_ago
                )
            )
            .options(selectinload(Task.assignee))
        )
        completed_tasks = (await session.execute(completed_q)).scalars().all()

        # 3. Query tasks currently blocked
        blocked_q = (
            select(Task)
            .join(Channel)
            .join(Project)
            .where(and_(Project.server_id == server_id, Task.status == "Blocked"))
            .options(selectinload(Task.assignee))
        )
        blocked_tasks = (await session.execute(blocked_q)).scalars().all()

        # 4. Compute assignee leaderboard (tasks completed in the last 7 days)
        leaderboard_data = {}
        for t in completed_tasks:
            name = t.assignee.display_name if t.assignee else "Unassigned"
            leaderboard_data[name] = leaderboard_data.get(name, 0) + 1
        
        sorted_leaderboard = sorted(leaderboard_data.items(), key=lambda x: x[1], reverse=True)[:5]

        # 5. Assemble Embed
        embed = discord.Embed(
            title="📊 IIT Bombay Racing - Weekly Operations Review",
            description=f"Performance summary for server `{server_id}` over the last 7 days.",
            color=discord.Color.brand_green(),
            timestamp=now
        )

        # Overview Stats
        stats_val = (
            f"📈 **Completion Rate**: `{metrics['COMPLETION_RATE']:.1f}%`\n"
            f"✅ **Total Completed Tasks**: `{int(metrics['COMPLETED_TASKS'])}` (`{len(completed_tasks)}` this week)\n"
            f"⚙️ **In Progress Backlog**: `{int(metrics['IN_PROGRESS_TASKS'])}` tasks\n"
            f"🚨 **Overdue Right Now**: `{int(metrics['OVERDUE_TASKS'])}` tasks\n"
            f"⏱️ **Average Lead Time**: `{metrics['AVG_COMPLETION_TIME_HOURS']:.1f} hours`"
        )
        embed.add_field(name="📋 Status Overview", value=stats_val, inline=False)

        # Leaderboard
        if sorted_leaderboard:
            lb_val = "\n".join([f"{i+1}. **{name}** — completed `{count}` tasks" for i, (name, count) in enumerate(sorted_leaderboard)])
        else:
            lb_val = "*No tasks completed this week.*"
        embed.add_field(name="🏆 Weekly Leaderboard", value=lb_val, inline=False)

        # Blocked Tasks
        if blocked_tasks:
            blocked_val = "\n".join([f"• **{t.title}** ({t.assignee.display_name if t.assignee else 'Unassigned'}) — *{t.blocked_reason or 'No reason provided'}*" for t in blocked_tasks[:5]])
        else:
            blocked_val = "*No blocked tasks currently!*"
        embed.add_field(name="🛑 Currently Blocked Tasks", value=blocked_val, inline=False)

        embed.set_footer(text="Weekly Performance Report • Analytics Engine V1")
        return embed

    async def generate_monthly_report(self, server_id: str, session: AsyncSession) -> discord.Embed:
        """Assembles monthly review: monthly trends, overall progress, top contributors."""
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        sixty_days_ago = now - timedelta(days=60)

        # Calculate metrics
        metrics = await self.calculate_server_metrics(server_id, session)

        # Query completed tasks in the last 30 days
        completed_q = (
            select(Task)
            .join(Channel)
            .join(Project)
            .where(
                and_(
                    Project.server_id == server_id,
                    Task.status.in_(["Done", "Completed"]),
                    Task.completed_time >= thirty_days_ago
                )
            )
            .options(selectinload(Task.assignee))
        )
        completed_tasks = (await session.execute(completed_q)).scalars().all()

        # Query completed tasks in the month before that
        prev_completed_q = (
            select(func.count(Task.id))
            .join(Channel)
            .join(Project)
            .where(
                and_(
                    Project.server_id == server_id,
                    Task.status.in_(["Done", "Completed"]),
                    Task.completed_time >= sixty_days_ago,
                    Task.completed_time < thirty_days_ago
                )
            )
        )
        prev_completed_count = (await session.execute(prev_completed_q)).scalar() or 0

        # Compute leaderboard
        leaderboard_data = {}
        for t in completed_tasks:
            name = t.assignee.display_name if t.assignee else "Unassigned"
            leaderboard_data[name] = leaderboard_data.get(name, 0) + 1
        sorted_leaderboard = sorted(leaderboard_data.items(), key=lambda x: x[1], reverse=True)[:5]

        diff_count = len(completed_tasks) - prev_completed_count
        trend_indicator = f"+{diff_count}" if diff_count >= 0 else str(diff_count)

        embed = discord.Embed(
            title="🏆 IIT Bombay Racing - Monthly Performance Digest",
            description=f"Monthly audit for server `{server_id}` over the last 30 days.",
            color=discord.Color.purple(),
            timestamp=now
        )

        stats_val = (
            f"📉 **Global Completion Rate**: `{metrics['COMPLETION_RATE']:.1f}%`\n"
            f"✅ **Completed in Last 30 Days**: `{len(completed_tasks)}` tasks (Trend: `{trend_indicator}` vs prev month)\n"
            f"👤 **Active Contributors**: `{int(metrics['ACTIVE_MEMBERS'])}` team members\n"
            f"⏱️ **Overall Average Lead Time**: `{metrics['AVG_COMPLETION_TIME_HOURS']:.1f} hours`"
        )
        embed.add_field(name="📈 Monthly Productivity Trends", value=stats_val, inline=False)

        if sorted_leaderboard:
            lb_val = "\n".join([f"{i+1}. **{name}** — completed `{count}` tasks" for i, (name, count) in enumerate(sorted_leaderboard)])
        else:
            lb_val = "*No tasks completed in the last 30 days.*"
        embed.add_field(name="🌟 Monthly Top Contributors", value=lb_val, inline=False)

        embed.set_footer(text="Monthly Performance Audit • Analytics Engine V1")
        return embed

    async def dispatch_weekly_reports(self) -> None:
        """Dispatches weekly review embeds to the report channels of all registered servers."""
        logger.info("Executing scheduled weekly report dispatch loop")
        
        async with self.bot.db_session() as session:
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
                        # Fallback: get first channel
                        channel_query = select(Channel).join(Project).where(Project.server_id == server_id).limit(1)
                        chan_result = await session.execute(channel_query)
                        chan = chan_result.scalar_one_or_none()
                        target_channel_id = chan.id if chan else None

                    if not target_channel_id:
                        continue

                    embed = await self.generate_weekly_report(server_id, session)

                channel = self.bot.get_channel(int(target_channel_id))
                if channel and isinstance(channel, discord.TextChannel):
                    await channel.send(embed=embed)
                    logger.info("Sent weekly operations report", server_id=server_id, channel=target_channel_id)
            except Exception as e:
                logger.error("Failed to dispatch weekly report", server_id=server_id, error=str(e))

    async def dispatch_monthly_reports(self) -> None:
        """Dispatches monthly review embeds to the report channels of all registered servers."""
        logger.info("Executing scheduled monthly report dispatch loop")

        async with self.bot.db_session() as session:
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
                        channel_query = select(Channel).join(Project).where(Project.server_id == server_id).limit(1)
                        chan_result = await session.execute(channel_query)
                        chan = chan_result.scalar_one_or_none()
                        target_channel_id = chan.id if chan else None

                    if not target_channel_id:
                        continue

                    embed = await self.generate_monthly_report(server_id, session)

                channel = self.bot.get_channel(int(target_channel_id))
                if channel and isinstance(channel, discord.TextChannel):
                    await channel.send(embed=embed)
                    logger.info("Sent monthly operations report", server_id=server_id, channel=target_channel_id)
            except Exception as e:
                logger.error("Failed to dispatch monthly report", server_id=server_id, error=str(e))

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
import uuid
import structlog

from backend.models.core import Task, Channel, Project, AssigneeMapping, History, ActivityLog
from backend.modules.tasks.repository import TaskRepository
from backend.services.analytics_service import AnalyticsService

logger = structlog.get_logger(__name__)


class TasksCog(commands.Cog):
    """Cog registering Task management, Work Reports, and Analytics commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="work_report", description="Generate and post a report of work completed by the team")
    @app_commands.describe(
        status="Filter tasks by status (default: Done)",
        member="Filter tasks by assigned CT member",
        public="Post report publicly to channel (default: True)"
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Completed / Done", value="Done"),
            app_commands.Choice(name="In Progress", value="In Progress"),
            app_commands.Choice(name="Blocked", value="Blocked"),
            app_commands.Choice(name="All Tasks", value="All"),
        ]
    )
    async def work_report(
        self,
        interaction: discord.Interaction,
        status: str = "Done",
        member: discord.Member | None = None,
        public: bool = True
    ) -> None:
        """Generates and posts a detailed report of work done / completed tasks."""
        await interaction.response.defer(ephemeral=not public)
        guild_id = str(interaction.guild_id)

        async with self.bot.db_session() as session:
            # Base query joining channel & project
            query = (
                select(Task)
                .join(Channel)
                .join(Project)
                .where(Project.server_id == guild_id)
                .options(
                    selectinload(Task.assignee),
                    selectinload(Task.channel).selectinload(Channel.project),
                    selectinload(Task.history),
                    selectinload(Task.activity_logs),
                )
            )

            # Filters
            filters = []
            if status != "All":
                if status == "Done":
                    filters.append(Task.status.in_(["Done", "Completed"]))
                else:
                    filters.append(Task.status == status)

            if member:
                # Look up assignee mapping by discord user id
                mapping_query = select(AssigneeMapping.id).where(
                    and_(
                        AssigneeMapping.server_id == guild_id,
                        AssigneeMapping.discord_user_id == str(member.id)
                    )
                )
                mapping_id = (await session.execute(mapping_query)).scalar_one_or_none()
                if mapping_id:
                    filters.append(Task.assignee_id == mapping_id)
                else:
                    # User not mapped — return empty result notice
                    embed = discord.Embed(
                        title="📋 Work Report",
                        description=f"No mapped tasks found for {member.mention}.",
                        color=discord.Color.gold()
                    )
                    await interaction.followup.send(embed=embed, ephemeral=not public)
                    return

            if filters:
                query = query.where(and_(*filters))

            tasks = (await session.execute(query)).scalars().all()

            # Format report embed
            status_title = "Completed Work" if status == "Done" else f"{status} Work"
            member_suffix = f" for {member.display_name}" if member else ""
            
            embed = discord.Embed(
                title=f"📊 IIT Bombay Racing — {status_title} Report{member_suffix}",
                description=f"Overview of **{len(tasks)} task(s)** matching criteria.",
                color=discord.Color.brand_green() if status in ("Done", "All") else (
                    discord.Color.red() if status == "Blocked" else discord.Color.gold()
                ),
                timestamp=datetime.now(timezone.utc)
            )

            if not tasks:
                embed.add_field(
                    name="No Tasks Found",
                    value=f"No tasks currently marked as `{status}`.",
                    inline=False
                )
            else:
                for idx, t in enumerate(tasks[:10], 1):
                    assignee_str = t.assignee.display_name if t.assignee else "Unassigned"
                    comp_time_str = t.completed_time.strftime("%d %b %Y • %I:%M %p IST") if t.completed_time else "N/A"
                    
                    details = [
                        f"👤 **CT Assignee**: `{assignee_str}`",
                        f"🎯 **Priority**: `{t.priority}`  •  **Status**: `{t.status}`",
                    ]

                    if t.completed_time:
                        details.append(f"⏱️ **Completed At**: `{comp_time_str}`")

                    if t.progress_summary:
                        details.append(f"📈 **Progress**: *{t.progress_summary[:200]}*")

                    if t.completion_summary:
                        details.append(f"✅ **Completion Summary**: {t.completion_summary[:300]}")

                    if t.blocked_reason:
                        details.append(f"🛑 **Blocked Reason**: {t.blocked_reason[:200]}")

                    details.append(f"📊 **Audit Trail**: `{len(t.history)}` revisions  •  `{len(t.activity_logs)}` activity events")

                    # Resource Links
                    links = []
                    if t.drive_links:
                        for i, url in enumerate(t.drive_links[:2], 1):
                            links.append(f"[Drive {i}]({url})")
                    if t.github_links:
                        for i, url in enumerate(t.github_links[:2], 1):
                            links.append(f"[GitHub {i}]({url})")
                    if links:
                        details.append(f"🔗 **Deliverables**: " + "  •  ".join(links))

                    embed.add_field(
                        name=f"{idx}. 📋 {t.title}",
                        value="\n".join(details)[:1024],
                        inline=False
                    )

                if len(tasks) > 10:
                    embed.set_footer(text=f"Showing top 10 of {len(tasks)} total tasks  •  Operations Analytics")
                else:
                    embed.set_footer(text="IIT Bombay Racing Operations Platform  •  Real-Time Analytics")

            await interaction.followup.send(embed=embed, ephemeral=not public)

    @app_commands.command(name="task_log", description="View the update count and full activity history of a task")
    @app_commands.describe(
        task_id="The UUID of the task or part of the task title"
    )
    async def task_log(self, interaction: discord.Interaction, task_id: str) -> None:
        """Displays update counts and activity log history for a specific task."""
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        async with self.bot.db_session() as session:
            task_repo = TaskRepository(session)
            clean_input = task_id.strip()
            
            # Try searching by UUID, short UUID prefix, or title match
            target_task = None
            if len(clean_input) == 36:
                try:
                    task_uuid = uuid.UUID(clean_input)
                    target_task = await task_repo.get_by_id(task_uuid)
                except ValueError:
                    pass

            if not target_task:
                from sqlalchemy import cast, String, or_
                query = (
                    select(Task)
                    .join(Channel)
                    .join(Project)
                    .where(
                        and_(
                            Project.server_id == guild_id,
                            or_(
                                cast(Task.id, String).ilike(f"{clean_input}%"),
                                Task.title.ilike(f"%{clean_input}%")
                            )
                        )
                    )
                    .options(
                        selectinload(Task.assignee),
                        selectinload(Task.history),
                        selectinload(Task.activity_logs)
                    )
                    .limit(1)
                )
                target_task = (await session.execute(query)).scalar_one_or_none()

            if not target_task:
                await interaction.followup.send(
                    f"❌ Task matching `{task_id}` not found.", ephemeral=True
                )
                return

            assignee_str = target_task.assignee.display_name if target_task.assignee else "Unassigned"

            embed = discord.Embed(
                title=f"📜 Audit Log & Revisions — {target_task.title}",
                description=(
                    f"👤 **Assignee**: `{assignee_str}`\n"
                    f"📌 **Status**: `{target_task.status}`  •  **Priority**: `{target_task.priority}`\n"
                    f"🔄 **Total Property Updates**: `{len(target_task.history)}` revisions\n"
                    f"⚡ **Total Activity Events**: `{len(target_task.activity_logs)}` events\n"
                    f"✏️ **Last Updated By**: `{target_task.updated_by or 'Notion Sync'}`"
                ),
                color=discord.Color.blurple(),
                timestamp=datetime.now(timezone.utc)
            )

            # Activity log highlights
            if target_task.activity_logs:
                log_lines = []
                for act in sorted(target_task.activity_logs, key=lambda x: x.created_at, reverse=True)[:5]:
                    dt_str = act.created_at.strftime("%d %b %H:%M")
                    log_lines.append(f"• `[{dt_str}]` **{act.action_type}** by <@{act.user_id}>: *{act.details[:80] if act.details else 'No detail'}*")
                embed.add_field(name="⚡ Recent Activity Logs", value="\n".join(log_lines), inline=False)

            # Property history highlights
            if target_task.history:
                hist_lines = []
                for h in sorted(target_task.history, key=lambda x: x.changed_at, reverse=True)[:5]:
                    dt_str = h.changed_at.strftime("%d %b %H:%M")
                    hist_lines.append(f"• `[{dt_str}]` **{h.property_name}**: `{h.old_value}` → `{h.new_value}` (*by {h.changed_by}*)")
                embed.add_field(name="🔄 Recent Property Changes", value="\n".join(hist_lines), inline=False)

            embed.set_footer(text=f"Task ID: {str(target_task.id)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="analytics", description="View server-wide operations metrics and productivity statistics")
    async def analytics_command(self, interaction: discord.Interaction) -> None:
        """Calculates and displays real-time server analytics."""
        await interaction.response.defer()
        guild_id = str(interaction.guild_id)

        async with self.bot.db_session() as session:
            analytics_svc = AnalyticsService(self.bot)
            metrics = await analytics_svc.calculate_server_metrics(guild_id, session)

            embed = discord.Embed(
                title="📈 Operations Analytics & Productivity",
                description=f"Live metrics for server `{interaction.guild.name if interaction.guild else guild_id}`.",
                color=discord.Color.purple(),
                timestamp=datetime.now(timezone.utc)
            )

            embed.add_field(
                name="🎯 Completion Rate",
                value=f"`{metrics['COMPLETION_RATE']:.1f}%`",
                inline=True
            )
            embed.add_field(
                name="✅ Completed Tasks",
                value=f"`{int(metrics['COMPLETED_TASKS'])}` tasks",
                inline=True
            )
            embed.add_field(
                name="⚙️ In Progress",
                value=f"`{int(metrics['IN_PROGRESS_TASKS'])}` tasks",
                inline=True
            )
            embed.add_field(
                name="🛑 Blocked Tasks",
                value=f"`{int(metrics['BLOCKED_TASKS'])}` tasks",
                inline=True
            )
            embed.add_field(
                name="🚨 Overdue Tasks",
                value=f"`{int(metrics['OVERDUE_TASKS'])}` tasks",
                inline=True
            )
            embed.add_field(
                name="👤 Active Contributors",
                value=f"`{int(metrics['ACTIVE_MEMBERS'])}` CT members",
                inline=True
            )
            embed.add_field(
                name="⏱️ Avg Lead Time",
                value=f"`{metrics['AVG_COMPLETION_TIME_HOURS']:.1f} hours`",
                inline=False
            )

            embed.set_footer(text="IIT Bombay Racing Operations Platform • Analytics Engine V1")
            await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TasksCog(bot))

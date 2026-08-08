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

logger = structlog.get_logger(__name__)


class TasksCog(commands.Cog):
    """Cog registering Task management commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

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

    @app_commands.command(name="add_task", description="Create a new task directly from Discord and sync it to Notion")
    @app_commands.describe(
        title="1. Task Name",
        status="2. Status (default: Not Started)",
        assigned_to="3. Assigned to (e.g. @Srikar, @Narayana or Srikar, Narayana)",
        assigned_by="4. Assigned By (Discord member, default: You)",
        due_date="5. Date (e.g. 2026-08-10, 10 Aug 2026, tomorrow, today)",
        description="6. Description (task details/notes)",
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(name="⚪ Not Started", value="Not Started"),
            app_commands.Choice(name="🟡 In Progress", value="In Progress"),
            app_commands.Choice(name="🔴 Blocked", value="Blocked"),
            app_commands.Choice(name="🟢 Done", value="Done"),
        ]
    )
    async def add_task(
        self,
        interaction: discord.Interaction,
        title: str,
        status: str = "Not Started",
        assigned_to: str | None = None,
        assigned_by: discord.Member | None = None,
        due_date: str = "today",
        description: str | None = None,
    ) -> None:
        """Creates a new task directly from Discord and syncs it to Notion."""
        await interaction.response.defer(ephemeral=False)
        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)

        # 1. Parse date
        parsed_due = parse_human_date_string(due_date)
        if not parsed_due:
            embed = discord.Embed(
                title="❌ Invalid Date Format",
                description=(
                    f"Could not parse due date `{due_date}`.\n\n"
                    "**Supported Formats:**\n"
                    "• `tomorrow` or `today`\n"
                    "• `2026-08-10` (YYYY-MM-DD)\n"
                    "• `10 Aug 2026` or `10 Aug`\n"
                    "• `10/08/2026` or `10-08-2026`"
                ),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        async with self.bot.db_session() as session:
            from backend.modules.projects.repository import ChannelRepository
            from backend.modules.settings.repository import AssigneeMappingRepository
            channel_repo = ChannelRepository(session)
            assignee_repo = AssigneeMappingRepository(session)

            # 2. Check channel mapping
            channel = await channel_repo.get_by_id(channel_id)
            if not channel or not channel.notion_database_id:
                embed = discord.Embed(
                    title="❌ Channel Not Integrated",
                    description="This channel is not mapped to a Notion database. Please run `/integrate_channel` first.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # 3. Resolve Assigned to (Supports multiple members via @mentions or comma-separated names)
            assignee_names: list[str] = []
            if assigned_to:
                import re
                mentioned_ids = re.findall(r'<@!?(\d+)>', assigned_to)
                for uid in mentioned_ids:
                    mapping = await assignee_repo.get_by_discord_user_id(guild_id, uid)
                    name_val = mapping.notion_user_id or mapping.display_name if mapping else None
                    if not name_val and interaction.guild:
                        m = interaction.guild.get_member(int(uid))
                        if m:
                            name_val = m.display_name
                    if name_val and name_val not in assignee_names:
                        assignee_names.append(name_val)

                raw_parts = [re.sub(r'<@!?\d+>', '', p).strip() for p in assigned_to.split(",") if p.strip()]
                for part in raw_parts:
                    if part and part not in assignee_names:
                        mapping = await assignee_repo.get_by_notion_user_id(guild_id, part, part)
                        name_val = mapping.notion_user_id or mapping.display_name if mapping else part
                        if name_val not in assignee_names:
                            assignee_names.append(name_val)

            assignee_notion_name = ", ".join(assignee_names) if assignee_names else None

            # 4. Resolve Assigned By
            target_assigner = assigned_by or interaction.user
            creator_mapping = await assignee_repo.get_by_discord_user_id(guild_id, str(target_assigner.id))
            creator_notion_name = creator_mapping.notion_user_id if creator_mapping else target_assigner.display_name

            # 5. Push page creation to Notion
            from backend.services.notion_service import NotionService
            notion = NotionService()

            notion_payload = {
                "title": title.strip(),
                "description": description.strip() if description else "",
                "status": status,
                "priority": "Medium",
                "due_date": parsed_due,
                "notion_assignee_name": assignee_notion_name,
                "assigned_by_name": creator_notion_name,
            }
            properties = notion.build_task_properties(notion_payload)

            try:
                page_res = await notion.create_page(channel.notion_database_id, properties)
            except Exception as ne:
                logger.error("Failed to create task page in Notion", error=str(ne))
                embed = discord.Embed(
                    title="❌ Notion Creation Failed",
                    description=f"Failed to create task in Notion: {ne}",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # 6. Trigger sync engine to persist task and create Discord card
            from backend.sync.sync_engine import SyncEngine
            sync = SyncEngine(self.bot)
            await sync.sync_channel(channel_id)

        await interaction.followup.send(
            content=f"✅ Task **{title}** created successfully and synced to Notion!",
            ephemeral=True
        )


def parse_human_date_string(date_str: str) -> datetime | None:
    """Parses user input date strings into a UTC datetime."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    raw = date_str.strip().lower()
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    
    if raw == "today":
        dt = now_ist.replace(hour=23, minute=59, second=59, microsecond=0)
        return dt.astimezone(timezone.utc)
    elif raw == "tomorrow":
        dt = (now_ist + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
        return dt.astimezone(timezone.utc)
        
    formats = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%d %b",
        "%d %B",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str.strip(), fmt)
            if fmt in ("%d %b", "%d %B"):
                parsed = parsed.replace(year=now_ist.year)
            dt = parsed.replace(hour=23, minute=59, second=59, tzinfo=ZoneInfo("Asia/Kolkata"))
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
            
    return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TasksCog(bot))

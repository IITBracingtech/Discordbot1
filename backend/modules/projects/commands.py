import discord
from discord.ext import commands
from discord import app_commands
from backend.utils.permissions import has_operation_role
from backend.models.core import Project, Channel, SyncState
import uuid

class ProjectsCog(commands.Cog):
    """Cog registering Project and Channel mapping commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="integrate_channel", description="Link a Discord channel to a Notion database")
    @app_commands.describe(
        database_id="The Notion Database ID to link",
        project_name="The name of the project this channel belongs to"
    )
    @has_operation_role("Manager")
    async def integrate_channel(
        self, interaction: discord.Interaction, database_id: str, project_name: str
    ) -> None:
        """Map a Notion Database to the current Discord channel."""
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        database_id = database_id.strip()

        async with self.bot.db_session() as session:
            from backend.modules.projects.repository import ProjectRepository, ChannelRepository
            project_repo = ProjectRepository(session)
            channel_repo = ChannelRepository(session)

            # Check if channel already mapped
            existing_channel = await channel_repo.get_by_id(channel_id)
            if existing_channel:
                existing_channel.notion_database_id = database_id
                if existing_channel.sync_state:
                    existing_channel.sync_state.notion_cursor = None
                else:
                    sync_state = SyncState(
                        channel_id=channel_id,
                        notion_cursor=None,
                        status="IDLE"
                    )
                    session.add(sync_state)
                await session.commit()
                embed = discord.Embed(
                    title="Channel Mapping Updated",
                    description=f"Successfully updated this channel to Notion Database `{database_id}`.",
                    color=discord.Color.brand_green()
                )
                embed.set_footer(text="IIT Bombay Racing Operations Platform")
                await interaction.followup.send(embed=embed)
                return

            # 0. Ensure Server record exists
            from backend.models.core import Server
            from sqlalchemy import select
            server_res = await session.execute(select(Server).where(Server.id == guild_id))
            server = server_res.scalar_one_or_none()
            if not server:
                guild_name = interaction.guild.name if interaction.guild else "Discord Server"
                server = Server(id=guild_id, name=guild_name)
                session.add(server)
                await session.flush()

            # Find or create project
            projects = await project_repo.get_by_server_id(guild_id)
            project = next((p for p in projects if p.name.lower() == project_name.lower()), None)

            if not project:
                project = Project(
                    id=uuid.uuid4(),
                    server_id=guild_id,
                    name=project_name
                )
                session.add(project)

            # Create channel mapping
            new_channel = Channel(
                id=channel_id,
                project_id=project.id,
                notion_database_id=database_id
            )
            session.add(new_channel)

            # Initialize sync state
            sync_state = SyncState(
                channel_id=channel_id,
                notion_cursor=None,
                status="IDLE"
            )
            session.add(sync_state)

            await session.commit()

        embed = discord.Embed(
            title="Channel Integrated",
            description=f"Successfully linked this channel to Notion Database `{database_id}` under project **{project.name}**.",
            color=discord.Color.brand_green()
        )
        embed.set_footer(text="IIT Bombay Racing Operations Platform")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProjectsCog(bot))

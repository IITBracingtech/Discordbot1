import discord
from discord.ext import commands
from discord import app_commands
from backend.utils.permissions import has_operation_role

class SettingsCog(commands.Cog):
    """Cog registering Settings and user mappings."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="link_assignee", description="Map a Notion User ID to a Discord User for assignee mentions")
    @app_commands.describe(
        notion_user_id="The Notion User Object ID",
        discord_user="The corresponding Discord Member"
    )
    @has_operation_role("Lead")  # Leads or above can define team mapping records
    async def link_assignee(
        self, interaction: discord.Interaction, notion_user_id: str, discord_user: discord.Member
    ) -> None:
        """Map a Notion User ID to a Discord Member."""
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        async with self.bot.db_session() as session:
            from backend.modules.settings.repository import AssigneeMappingRepository
            repo = AssigneeMappingRepository(session)
            await repo.link_assignee(
                server_id=guild_id,
                discord_user_id=str(discord_user.id),
                notion_user_id=notion_user_id.strip(),
                display_name=discord_user.display_name
            )
            await session.commit()

        embed = discord.Embed(
            title="Assignee Mapping Linked",
            description=f"Successfully mapped Notion User ID `{notion_user_id}` to Discord member {discord_user.mention}.",
            color=discord.Color.brand_green()
        )
        embed.set_footer(text="IIT Bombay Racing Operations Platform")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="link_account", description="Link a Discord member and automatically add them to the Notion dropdown")
    @app_commands.describe(
        discord_user="The Discord member to link and add to the Notion dropdown",
        notion_name="Optional custom Notion dropdown tag (defaults to Discord member display name)"
    )
    async def link_account(
        self,
        interaction: discord.Interaction,
        discord_user: discord.Member,
        notion_name: str | None = None
    ) -> None:
        """Map a Discord Member and push their name into all mapped Notion dropdowns."""
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        target_name = notion_name.strip() if notion_name else discord_user.display_name

        async with self.bot.db_session() as session:
            from backend.modules.settings.repository import AssigneeMappingRepository
            from backend.models.core import Channel, Project
            from backend.services.notion_service import NotionService
            from sqlalchemy import select

            repo = AssigneeMappingRepository(session)
            await repo.link_assignee(
                server_id=guild_id,
                discord_user_id=str(discord_user.id),
                notion_user_id=target_name,
                display_name=discord_user.display_name
            )
            await session.commit()

            # Push the member's name to all mapped Notion database dropdowns in this server
            query = select(Channel).join(Project).where(Project.server_id == guild_id)
            channels = (await session.execute(query)).scalars().all()

            notion_svc = NotionService()
            added_count = 0
            for channel in channels:
                if channel.notion_database_id:
                    # Push to Assigned to
                    await notion_svc.add_select_option_to_database(
                        channel.notion_database_id,
                        "Assigned to",
                        target_name
                    )
                    # Push to Assigned By
                    await notion_svc.add_select_option_to_database(
                        channel.notion_database_id,
                        "Assigned By",
                        target_name
                    )
                    added_count += 1

        embed = discord.Embed(
            title="✅ Account Linked & Added to Notion Dropdowns!",
            description=(
                f"Successfully linked {discord_user.mention} to Notion tag **`{target_name}`**!\n\n"
                f"📥 **Notion Dropdowns Updated:** Added **`{target_name}`** to both `Assigned to` and `Assigned By` dropdowns in Notion.\n\n"
                f"Now when you select **`{target_name}`** in Notion, the bot will recognize them!"
            ),
            color=discord.Color.brand_green()
        )
        embed.set_footer(text="IIT Bombay Racing Operations Platform")
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))

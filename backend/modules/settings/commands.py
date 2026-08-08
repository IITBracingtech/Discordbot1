import discord
from discord.ext import commands
from discord import app_commands

class SettingsCog(commands.Cog):
    """Cog registering Settings and user mappings."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

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

    @app_commands.command(name="sync_members", description="Bulk link all 30-50 team members or specific Discord roles to Notion dropdowns")
    @app_commands.describe(
        role="Optional Discord role to filter (e.g. @AMs, @Managers, @Mech DE). Leave empty to sync all members."
    )
    async def sync_members(
        self,
        interaction: discord.Interaction,
        role: discord.Role | None = None
    ) -> None:
        """Bulk link all members or specific role members and populate Notion dropdowns."""
        await interaction.response.defer(ephemeral=False)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ This command must be used inside a Discord server.", ephemeral=True)
            return

        guild_id = str(guild.id)
        members_to_sync = role.members if role else guild.members
        human_members = [m for m in members_to_sync if not m.bot]

        if not human_members:
            await interaction.followup.send("⚠️ No human members found to sync.", ephemeral=True)
            return

        async with self.bot.db_session() as session:
            from backend.modules.settings.repository import AssigneeMappingRepository
            from backend.models.core import Channel, Project
            from backend.services.notion_service import NotionService
            from sqlalchemy import select

            repo = AssigneeMappingRepository(session)
            synced_names: list[str] = []

            for member in human_members:
                display_name = member.display_name
                await repo.link_assignee(
                    server_id=guild_id,
                    discord_user_id=str(member.id),
                    notion_user_id=display_name,
                    display_name=display_name
                )
                if display_name not in synced_names:
                    synced_names.append(display_name)

            await session.commit()

            # Push all names to mapped Notion database dropdowns
            query = select(Channel).join(Project).where(Project.server_id == guild_id)
            channels = (await session.execute(query)).scalars().all()

            notion_svc = NotionService()
            pushed_count = 0
            for channel in channels:
                if channel.notion_database_id:
                    for name in synced_names:
                        await notion_svc.add_select_option_to_database(
                            channel.notion_database_id,
                            "Assigned to",
                            name
                        )
                        await notion_svc.add_select_option_to_database(
                            channel.notion_database_id,
                            "Assigned By",
                            name
                        )
                    pushed_count += 1

        role_info = f"with role **{role.name}**" if role else "in the server"
        embed = discord.Embed(
            title="⚡ Bulk Member Sync Completed!",
            description=(
                f"Successfully synced **{len(synced_names)} team members** {role_info}!\n\n"
                f"• Registered in Bot Database: **{len(synced_names)} members**\n"
                f"• Notion Databases Updated: **{pushed_count} databases**\n\n"
                f"All team members can now be tagged in Notion and assigned directly using `/add_task`!"
            ),
            color=discord.Color.brand_green()
        )
        embed.set_footer(text="IIT Bombay Racing Operations Platform")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))

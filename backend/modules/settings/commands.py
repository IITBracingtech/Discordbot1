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
        notion_name="Optional custom Notion dropdown tag (defaults to Discord member display name)",
        target_channel="Optional target channel/table to update (defaults to current channel)",
        all_databases="Set to True to update all Notion databases in the server instead of just this channel's table"
    )
    async def link_account(
        self,
        interaction: discord.Interaction,
        discord_user: discord.Member,
        notion_name: str | None = None,
        target_channel: discord.TextChannel | None = None,
        all_databases: bool = False
    ) -> None:
        """Map a Discord Member and push their name into the particular Notion database dropdown."""
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

            # Target particular table only unless all_databases is True
            if all_databases:
                query = select(Channel).join(Project).where(Project.server_id == guild_id)
            else:
                target_ch_id = str(target_channel.id) if target_channel else str(interaction.channel_id)
                query = select(Channel).where(Channel.id == target_ch_id)

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

        if added_count > 0:
            scope_msg = f"in **{added_count} Notion database(s)**" if all_databases else "in the particular Notion database table linked to this channel"
            embed = discord.Embed(
                title="✅ Account Linked & Added to Notion Dropdown!",
                description=(
                    f"Successfully linked {discord_user.mention} to Notion tag **`{target_name}`**!\n\n"
                    f"📥 **Notion Dropdown Updated:** Added **`{target_name}`** to `Assigned to` and `Assigned By` {scope_msg}.\n\n"
                    f"Now when you select **`{target_name}`** in Notion, the bot will recognize them!"
                ),
                color=discord.Color.brand_green()
            )
        else:
            embed = discord.Embed(
                title="✅ Account Linked (Local Mapping Created)",
                description=(
                    f"Successfully linked {discord_user.mention} to Notion tag **`{target_name}`** in bot database.\n\n"
                    f"⚠️ **Note:** The target channel is not integrated with a Notion database table. Notion dropdowns were not updated. "
                    f"Run `/integrate_channel` to link a Notion table or pass `all_databases=True`."
                ),
                color=discord.Color.gold()
            )

        embed.set_footer(text="IIT Bombay Racing Operations Platform")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="sync_members", description="Bulk link team members or specific Discord roles to Notion dropdowns")
    @app_commands.describe(
        role="Optional Discord role to filter (e.g. @AMs, @Managers, @Mech DE). Leave empty to sync all members.",
        target_channel="Optional target channel/table to update (defaults to current channel)",
        all_databases="Set to True to update all Notion databases in the server instead of just this channel's table"
    )
    async def sync_members(
        self,
        interaction: discord.Interaction,
        role: discord.Role | None = None,
        target_channel: discord.TextChannel | None = None,
        all_databases: bool = False
    ) -> None:
        """Bulk link members and populate the particular Notion database dropdown."""
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

            # Target particular table only unless all_databases is True
            if all_databases:
                query = select(Channel).join(Project).where(Project.server_id == guild_id)
            else:
                target_ch_id = str(target_channel.id) if target_channel else str(interaction.channel_id)
                query = select(Channel).where(Channel.id == target_ch_id)

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
        if pushed_count > 0:
            db_info = f"**{pushed_count} Notion database(s)**" if all_databases else "the particular Notion database table linked to this channel"
            embed = discord.Embed(
                title="⚡ Member Sync Completed!",
                description=(
                    f"Successfully synced **{len(synced_names)} team members** {role_info}!\n\n"
                    f"• Registered in Bot Database: **{len(synced_names)} members**\n"
                    f"• Notion Table Updated: {db_info}\n\n"
                    f"All team members can now be tagged in Notion and assigned directly using `/add_task`!"
                ),
                color=discord.Color.brand_green()
            )
        else:
            embed = discord.Embed(
                title="⚡ Member Sync Completed (Database Mapped Only)",
                description=(
                    f"Successfully registered **{len(synced_names)} team members** {role_info} in bot database.\n\n"
                    f"⚠️ **Note:** The channel is not integrated with a Notion database table. Dropdowns were not updated. "
                    f"Run `/integrate_channel` to link a Notion table or pass `all_databases=True`."
                ),
                color=discord.Color.gold()
            )

        embed.set_footer(text="IIT Bombay Racing Operations Platform")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="unsync_members", description="Remove synced team members or specific roles from a Notion table dropdown")
    @app_commands.describe(
        role="Optional Discord role to remove (e.g. @AMs, @Managers, @Mech DE). Leave empty to remove specified member or all.",
        member="Optional specific member to remove from the Notion dropdown",
        target_channel="Optional target channel/table to update (defaults to current channel)",
        all_databases="Set to True to remove options from all Notion databases in the server instead of just this channel's table"
    )
    async def unsync_members(
        self,
        interaction: discord.Interaction,
        role: discord.Role | None = None,
        member: discord.Member | None = None,
        target_channel: discord.TextChannel | None = None,
        all_databases: bool = False
    ) -> None:
        """Remove synced member names from a particular Notion database dropdown."""
        await interaction.response.defer(ephemeral=False)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ This command must be used inside a Discord server.", ephemeral=True)
            return

        guild_id = str(guild.id)
        names_to_remove: list[str] = []

        if member:
            names_to_remove.append(member.display_name)
        elif role:
            names_to_remove = [m.display_name for m in role.members if not m.bot]
        else:
            names_to_remove = [m.display_name for m in guild.members if not m.bot]

        if not names_to_remove:
            await interaction.followup.send("⚠️ No member names found to remove.", ephemeral=True)
            return

        async with self.bot.db_session() as session:
            from backend.models.core import Channel, Project
            from backend.services.notion_service import NotionService
            from sqlalchemy import select

            if all_databases:
                query = select(Channel).join(Project).where(Project.server_id == guild_id)
            else:
                target_ch_id = str(target_channel.id) if target_channel else str(interaction.channel_id)
                query = select(Channel).where(Channel.id == target_ch_id)

            channels = (await session.execute(query)).scalars().all()
            if not channels:
                await interaction.followup.send(
                    "❌ No integrated Notion database found for this channel. Please run `/integrate_channel` first.",
                    ephemeral=True
                )
                return

            notion_svc = NotionService()
            updated_count = 0
            for channel in channels:
                if channel.notion_database_id:
                    r1 = await notion_svc.remove_select_options_from_database(
                        channel.notion_database_id,
                        "Assigned to",
                        names_to_remove
                    )
                    r2 = await notion_svc.remove_select_options_from_database(
                        channel.notion_database_id,
                        "Assigned By",
                        names_to_remove
                    )
                    if r1 or r2:
                        updated_count += 1

        filter_info = f"for member **{member.display_name}**" if member else (f"for role **{role.name}**" if role else "for all team members")
        target_info = "all Notion databases in server" if all_databases else f"the particular Notion database table linked to this channel"

        embed = discord.Embed(
            title="🗑️ Unsync Members Completed!",
            description=(
                f"Successfully removed **{len(names_to_remove)} member tag(s)** {filter_info} from Notion dropdowns!\n\n"
                f"• Target Scope: **{target_info}**\n"
                f"• Notion Databases Updated: **{updated_count} database(s)**"
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text="IIT Bombay Racing Operations Platform")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))


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

    @app_commands.command(name="sync_members", description="Bulk link team members or filter by multiple Discord roles to a Notion table")
    @app_commands.describe(
        role="Primary Discord role to filter (e.g. @Mech)",
        role2="Secondary Discord role filter (e.g. @DE, to match members having BOTH @Mech and @DE)",
        role3="Third Discord role filter if needed",
        target_channel="Optional target channel/table to update (defaults to current channel)",
        all_databases="Set to True to update all Notion databases in the server instead of just this channel's table"
    )
    async def sync_members(
        self,
        interaction: discord.Interaction,
        role: discord.Role | None = None,
        role2: discord.Role | None = None,
        role3: discord.Role | None = None,
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
        selected_roles = [r for r in [role, role2, role3] if r is not None]

        if selected_roles:
            members_to_sync = [m for m in guild.members if all(r in m.roles for r in selected_roles)]
        else:
            members_to_sync = guild.members

        human_members = [m for m in members_to_sync if not m.bot]

        if not human_members:
            role_str = " + ".join([r.name for r in selected_roles]) if selected_roles else ""
            await interaction.followup.send(f"⚠️ No human members found matching role(s): **{role_str}**.", ephemeral=True)
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

        role_names = " + ".join([f"**@{r.name}**" for r in selected_roles])
        role_info = f"with tags {role_names}" if selected_roles else "in the server"
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
        role="Primary Discord role to remove (e.g. @Mech)",
        role2="Secondary Discord role filter (e.g. @DE, to match members having BOTH @Mech and @DE)",
        role3="Third Discord role filter if needed",
        member="Optional specific member to remove from the Notion dropdown",
        target_channel="Optional target channel/table to update (defaults to current channel)",
        all_databases="Set to True to remove options from all Notion databases in the server instead of just this channel's table"
    )
    async def unsync_members(
        self,
        interaction: discord.Interaction,
        role: discord.Role | None = None,
        role2: discord.Role | None = None,
        role3: discord.Role | None = None,
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
        selected_roles = [r for r in [role, role2, role3] if r is not None]
        names_to_remove: list[str] = []

        if member:
            names_to_remove.append(member.display_name)
        elif selected_roles:
            matched_members = [m for m in guild.members if all(r in m.roles for r in selected_roles)]
            names_to_remove = [m.display_name for m in matched_members if not m.bot]
        else:
            names_to_remove = [m.display_name for m in guild.members if not m.bot]

        if not names_to_remove:
            role_str = " + ".join([r.name for r in selected_roles]) if selected_roles else ""
            await interaction.followup.send(f"⚠️ No member names found matching role(s): **{role_str}**.", ephemeral=True)
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

        role_names = " + ".join([f"**@{r.name}**" for r in selected_roles])
        filter_info = f"for member **{member.display_name}**" if member else (f"for tags {role_names}" if selected_roles else "for all team members")
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

    @app_commands.command(name="export_roster", description="Export team roster (Name - Roles) to PDF & CSV for data analysis and updating roles")
    @app_commands.describe(
        role="Optional Discord role to filter (e.g. @Mech, @DE, @AMs)",
        file_format="Export format: PDF Document (.pdf), CSV Spreadsheet (.csv), or Both"
    )
    @app_commands.choices(
        file_format=[
            app_commands.Choice(name="📄 PDF Document (.pdf)", value="pdf"),
            app_commands.Choice(name="📊 CSV Spreadsheet (.csv)", value="csv"),
            app_commands.Choice(name="📦 Both PDF & CSV (.pdf + .csv)", value="both"),
        ]
    )
    async def export_roster(
        self,
        interaction: discord.Interaction,
        role: discord.Role | None = None,
        file_format: str = "pdf"
    ) -> None:
        """Generates and uploads a PDF and/or CSV report of all members formatted as Name - Roles."""
        await interaction.response.defer(ephemeral=False)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ This command must be used inside a Discord server.", ephemeral=True)
            return

        try:
            # Ensure full member list is fetched if cache is cold
            all_members = guild.members
            if len(all_members) <= 1:
                try:
                    all_members = [m async for m in guild.fetch_members(limit=None)]
                except Exception as fe:
                    from structlog import get_logger
                    get_logger(__name__).warning("Could not fetch members via API, using cached members", error=str(fe))
                    all_members = guild.members

            # Fetch non-bot members
            if role:
                members = [m for m in all_members if not m.bot and role in m.roles]
            else:
                members = [m for m in all_members if not m.bot]

            if not members:
                role_msg = f" with role **@{role.name}**" if role else ""
                await interaction.followup.send(f"⚠️ No human members found{role_msg}.", ephemeral=True)
                return

            # Build list of (Name, Roles)
            member_data: list[tuple[str, str]] = []
            for m in sorted(members, key=lambda x: (x.display_name or "").lower()):
                name = m.display_name or m.name
                roles = [r.name for r in m.roles if r.name != "@everyone"]
                roles_str = ", ".join(roles) if roles else "No Roles"
                member_data.append((name, roles_str))

            from backend.utils.roster_exporter import generate_roster_pdf, generate_roster_csv

            files_to_send: list[discord.File] = []
            suffix = f" ({role.name})" if role else ""

            if file_format in ("pdf", "both"):
                pdf_buf = generate_roster_pdf(guild.name, member_data, title_suffix=suffix)
                files_to_send.append(discord.File(pdf_buf, filename=f"Team_Roster_{guild.id}.pdf"))

            if file_format in ("csv", "both"):
                csv_buf = generate_roster_csv(member_data)
                files_to_send.append(discord.File(csv_buf, filename=f"Team_Roster_{guild.id}.csv"))

            filter_info = f"filtered by role **@{role.name}**" if role else "for all server members"
            embed = discord.Embed(
                title="📄 Team Roster & Roles Export Generated!",
                description=(
                    f"Successfully exported **{len(member_data)} team member(s)** {filter_info}!\n\n"
                    f"📋 **Format:** `Name - Roles` (e.g., `Srikar - Mech, DE`)\n"
                    f"📥 **Attachments:** Download the attached file(s) below for data analysis and role updates."
                ),
                color=discord.Color.blue()
            )
            embed.set_footer(text="IIT Bombay Racing Operations Platform")
            await interaction.followup.send(embed=embed, files=files_to_send)
        except Exception as e:
            from structlog import get_logger
            get_logger(__name__).error("Failed to generate export_roster", error=str(e), exc_info=True)
            await interaction.followup.send(
                f"❌ An error occurred generating the roster export: `{str(e)}`. Please try again.",
                ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))

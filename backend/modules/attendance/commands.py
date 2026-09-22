"""
Attendance module — slash command Cog for Discordbot1.

Registers:
  /leave   — log absence (auto-detected subsystem tab & cumulative total leaves)
  /flagged — (admin) show students with excess leave this week across subsystems
"""

import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from datetime import date
import structlog

from backend.config.settings import settings
from backend.modules.attendance.sheets import (
    parse_date_input,
    leave_exists,
    add_leave,
    detect_subsystem,
    get_week_bounds,
    get_weekly_leave_counts,
    get_user_leaves,
    get_flagged_users,
    init_sheets,
)

logger = structlog.get_logger(__name__)


async def _safe_defer(interaction: discord.Interaction, ephemeral: bool = False) -> None:
    if not interaction.response.is_done():
        try:
            await interaction.response.defer(ephemeral=ephemeral)
        except Exception:
            pass


async def _safe_send(interaction: discord.Interaction, content: str, ephemeral: bool = False) -> None:
    if interaction.response.is_done():
        try:
            await interaction.followup.send(content, ephemeral=ephemeral)
        except Exception as e:
            logger.warning("Followup send exception, retrying without ephemeral flag", error=str(e))
            try:
                await interaction.followup.send(content)
            except Exception as e2:
                logger.error("Failed fallback followup send", error=str(e2))
    else:
        try:
            await interaction.response.send_message(content, ephemeral=ephemeral)
        except Exception as e:
            logger.warning("Response send exception, retrying followup", error=str(e))
            try:
                await interaction.followup.send(content)
            except Exception as e2:
                logger.error("Failed fallback followup send", error=str(e2))


class AttendanceCog(commands.Cog):
    """Cog registering Attendance slash commands (/leave, /flagged)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        """Called automatically when cog is loaded. Ensures Sheets tab readiness."""
        try:
            await asyncio.to_thread(init_sheets)
            logger.info("AttendanceCog loaded and subsystem sheets initialized")
        except Exception as e:
            logger.warning("AttendanceCog loaded but Google Sheets init deferred", error=str(e))

    # ── /leave ────────────────────────────────────────────────────────────────

    @app_commands.command(name="leave", description="Log that you're on leave today (or another date).")
    @app_commands.describe(
        reason="Reason for your leave",
        leave_date="Date (YYYY-MM-DD), 'today', or 'tomorrow'. Defaults to today.",
    )
    async def leave(
        self,
        interaction: discord.Interaction,
        reason: str,
        leave_date: str | None = None,
    ) -> None:
        """Log a leave entry for the invoking user into their subsystem worksheet."""
        await _safe_defer(interaction)

        # 1. Detect subsystem role from member's assigned roles
        roles = interaction.user.roles if isinstance(interaction.user, discord.Member) else []
        subsystem = detect_subsystem(roles)

        if not subsystem:
            await _safe_send(
                interaction,
                "⚠️ You don't have a subsystem role assigned yet! Please check out the self-roles channel to select your subdivision first.",
                ephemeral=True,
            )
            return

        # 2. Parse date input
        try:
            parsed_date = parse_date_input(leave_date)
        except ValueError as e:
            await _safe_send(interaction, f"⚠️ {e}", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        username = str(interaction.user)

        # 3. Duplicate guard (non-blocking thread execution across all subsystem sheets)
        exists = await asyncio.to_thread(leave_exists, user_id, parsed_date)
        if exists:
            logger.info("Duplicate leave attempt", user_id=user_id, date=str(parsed_date))
            await _safe_send(
                interaction,
                f"ℹ️ {interaction.user.mention} already has leave logged for "
                f"**{parsed_date.strftime('%a, %d %b %Y')}**.",
                ephemeral=True,
            )
            return

        # 4. Record leave in the user's subsystem tab and calculate overall leaves
        new_total = await asyncio.to_thread(add_leave, user_id, username, parsed_date, reason, subsystem)

        # 5. Public confirmation with subsystem badge
        await _safe_send(
            interaction,
            f"📋 {interaction.user.mention} (`{subsystem}`) has been marked as absent on "
            f"**{parsed_date.strftime('%a, %d %b %Y')}** — reason: _{reason}_"
        )

    # ── /late (Disabled / Commented out for now) ──────────────────────────────
    """
    @app_commands.command(name="late", description="Log that you're late today (or another date).")
    @app_commands.describe(
        reason="Reason for being late",
        late_date="Date (YYYY-MM-DD), 'today', or 'tomorrow'. Defaults to today.",
    )
    async def late(
        self,
        interaction: discord.Interaction,
        reason: str,
        late_date: str | None = None,
    ) -> None:
        pass
    """

    # ── /flagged ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="flagged",
        description="(Admin) Show all students flagged for excess leave this week.",
    )
    async def flagged(self, interaction: discord.Interaction) -> None:
        """Display a list of students with >1 distinct leave day this week across all subsystem sheets."""
        # Permission check: Manage Server or Administrator
        if isinstance(interaction.user, discord.Member) and not (
            interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator
        ):
            await _safe_send(
                interaction,
                "❌ You need **Manage Server** permission to use this command.",
                ephemeral=True,
            )
            return

        await _safe_defer(interaction, ephemeral=True)

        week_start, week_end = get_week_bounds(date.today())
        flagged_list = await asyncio.to_thread(get_flagged_users, week_start, week_end)

        if not flagged_list:
            await _safe_send(
                interaction,
                f"✅ No students flagged this week "
                f"({week_start.strftime('%d %b')}–{week_end.strftime('%d %b')}).",
                ephemeral=True,
            )
            return

        lines = [
            f"**Flagged Students — Week of {week_start.strftime('%d %b')} to {week_end.strftime('%d %b')}**",
            f"*{len(flagged_list)} student(s) with more than 1 leave day this week*",
            "",
        ]
        for user_row, leaves in flagged_list:
            subsystem_tag = f" (`{user_row['subsystem']}`)" if user_row.get("subsystem") else ""
            lines.append(f"👤 **{user_row['username']}**{subsystem_tag} — {user_row['day_count']} day(s) this week")
            for lv in leaves:
                lines.append(f"  • `{lv['leave_date']}` — {lv['reason']}")
            lines.append("")

        await _safe_send(interaction, "\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Entry-point invoked by bot.load_extension()."""
    await bot.add_cog(AttendanceCog(bot))

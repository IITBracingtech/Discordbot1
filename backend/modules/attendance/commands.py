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

    # Slash command /leave has been replaced with Groq AI natural language tagging listener.
    # Users can now tag @Race Control to request a leave naturally in chat!

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

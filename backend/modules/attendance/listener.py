"""
Attendance module — event listener Cog for Discordbot1.

Listens for bot @mentions in chat messages and uses Groq LLM to automatically
extract leave requests, detect subsystem roles, check duplicates, and log to
Google Sheets.
"""

import asyncio
import time
import uuid
from collections import deque
from datetime import datetime, date
import discord
from discord.ext import commands
import structlog

from backend.modules.attendance.sheets import (
    detect_subsystem,
    leave_exists,
    add_leave,
    parse_date_input,
)
from backend.services.groq_service import groq_service

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level deduplication — survives across Cog re-instantiations.
# Maps message_id -> timestamp_processed so we can also expire old entries.
# ---------------------------------------------------------------------------
_PROCESSED_MSG_IDS: dict[int, float] = {}
_PROCESSED_MSG_TTL = 30  # seconds — enough to catch any double-fire window


class AttendanceListenerCog(commands.Cog):
    """Cog listening to chat messages for natural language attendance tagging (@bot)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming messages where the bot is mentioned."""
        invocation_id = str(uuid.uuid4())[:8]  # Unique ID per invocation for Render log tracing

        # 1. Ignore bot's own messages or other bot messages
        if message.author.bot:
            return

        logger.info("[TRACE] on_message fired", inv=invocation_id, msg_id=message.id, author=str(message.author))


        # 2. Deduplicate using module-level map — prevents double-fire even if
        #    cog is re-instantiated (e.g. on bot reconnect).
        now = time.monotonic()
        # Purge expired entries older than TTL
        expired = [mid for mid, ts in _PROCESSED_MSG_IDS.items() if now - ts > _PROCESSED_MSG_TTL]
        for mid in expired:
            _PROCESSED_MSG_IDS.pop(mid, None)

        if message.id in _PROCESSED_MSG_IDS:
            logger.warning("[TRACE] DUPLICATE on_message — blocked by dedup", inv=invocation_id, msg_id=message.id)
            return
        _PROCESSED_MSG_IDS[message.id] = now

        # 3. Check if the bot is tagged/mentioned
        if self.bot.user not in message.mentions and f"<@{self.bot.user.id}>" not in message.content:
            return

        # 4. Clean message content by stripping bot mention tag
        raw_text = message.content
        clean_text = raw_text.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()

        if not clean_text:
            await message.channel.send(f"Hello {message.author.mention}! How can I help you today?")
            return

        logger.info("Processing tagged message via Groq AI", author=str(message.author), inv=invocation_id, content=clean_text)

        # Trigger typing indicator while Groq processes
        async with message.channel.typing():
            # 4. Pass message to Groq LLM for intent & leave/late extraction
            logger.info("[TRACE] Calling Groq API", inv=invocation_id, msg_id=message.id)
            intent = await groq_service.parse_attendance_intent(clean_text)
            logger.info("[TRACE] Groq API responded", inv=invocation_id, intent=intent)

            # 5. Handle Attendance Intent (Leave or Late)
            if intent.get("is_attendance_request"):
                entry_type = intent.get("entry_type", "leave")
                leave_date_str = intent.get("date")
                reason = intent.get("reason") or "Not specified"

                # Parse date string to datetime.date
                try:
                    parsed_date = parse_date_input(leave_date_str)
                except ValueError:
                    parsed_date = date.today()

                # Detect subsystem role from member's assigned roles
                roles = message.author.roles if isinstance(message.author, discord.Member) else []
                subsystem = detect_subsystem(roles)

                # Guard: No subsystem role assigned
                if not subsystem:
                    await message.reply(
                        "⚠️ You don't have a subsystem role assigned yet! Please check out the self-roles channel to select your subdivision first.",
                        mention_author=True,
                    )
                    return

                user_id = str(message.author.id)
                username = str(message.author)

                # 1. Send Discord confirmation message IMMEDIATELY (sub-second response time!)
                if entry_type == "late":
                    reply_msg = (
                        f"⏰ {message.author.mention} (`{subsystem}`) will be late on "
                        f"**{parsed_date.strftime('%a, %d %b %Y')}** — reason: _{reason}_"
                    )
                else:
                    reply_msg = (
                        f"📋 {message.author.mention} (`{subsystem}`) has been marked as absent on "
                        f"**{parsed_date.strftime('%a, %d %b %Y')}** — reason: _{reason}_"
                    )

                await message.reply(reply_msg, mention_author=True)

                # 2. Update Google Sheets in background without keeping Discord waiting
                asyncio.create_task(
                    self._save_attendance_background(message, user_id, username, parsed_date, reason, subsystem, entry_type)
                )

            # 6. General Assistant Intent (Non-leave/late tag query)
            else:
                try:
                    if not groq_service.is_configured:
                        reply_text = (
                            f"Hello {message.author.mention}! I am **Race Control** 🏎️\n"
                            f"You can tag me to log leaves or lateness (e.g., `@Race Control on leave tomorrow` or `@Race Control coming 30m late`).\n\n"
                            f"*(Note: To enable full AI chat conversations, please set `GROQ_API_KEY` in Render!)*"
                        )
                    else:
                        system_prompt = (
                            "You are Race Control, the intelligent Discord bot for the IITB Racing Team. "
                            "Respond helpfully, politely, and concisely in 1-3 sentences."
                        )
                        reply_text = await groq_service.ask(clean_text, system_prompt=system_prompt)
                    await message.reply(reply_text, mention_author=True)
                except Exception as e:
                    logger.error("Failed to answer general bot mention", error=str(e))
                    await message.reply(
                        f"Hello {message.author.mention}! I am **Race Control**. You can tag me anytime to report leaves or lateness!",
                        mention_author=True,
                    )

    async def _save_attendance_background(
        self,
        message: discord.Message,
        user_id: str,
        username: str,
        parsed_date: date,
        reason: str,
        subsystem: str,
        entry_type: str = "leave",
    ) -> None:
        """Background worker: checks duplicates and writes leave/late to Google Sheets."""
        try:
            from backend.modules.attendance.sheets import is_sheets_configured, leave_exists, add_attendance_entry
            if not is_sheets_configured():
                logger.warning("Google Sheets credentials or SPREADSHEET_ID missing in environment variables")
                await message.channel.send(
                    f"⚠️ **Notice for Admins:** Google Sheets variables (`SPREADSHEET_ID` & `GOOGLE_SERVICE_ACCOUNT_JSON`) are not configured in Render. Please add them to sync attendance entries directly into your spreadsheet!",
                )
                return

            exists = await asyncio.to_thread(leave_exists, user_id, parsed_date, entry_type)
            if exists:
                logger.info("Duplicate attendance entry detected in background", user_id=user_id, date=str(parsed_date), type=entry_type)
                return

            await asyncio.to_thread(add_attendance_entry, user_id, username, parsed_date, reason, subsystem, entry_type)
            logger.info("Background Google Sheets update complete", user_id=user_id, date=str(parsed_date), type=entry_type)
        except Exception as e:
            logger.error("Error saving attendance to Google Sheets in background", error=str(e))


async def setup(bot: commands.Bot) -> None:
    """Entry point for dynamic cog loading by DiscordSyncBot."""
    await bot.add_cog(AttendanceListenerCog(bot))
    logger.info("AttendanceListenerCog loaded successfully")

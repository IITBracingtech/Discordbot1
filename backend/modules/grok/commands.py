"""
Grok AI module — slash command Cog for Discordbot1.

Registers:
  /grok  — Ask Grok AI any question or request code/summary/analysis
  /ask   — Alias slash command for Grok AI
"""

import discord
from discord.ext import commands
from discord import app_commands
import structlog

from backend.services.grok_service import grok_service

logger = structlog.get_logger(__name__)


class GrokCog(commands.Cog):
    """Cog registering Grok AI slash commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="grok",
        description="Ask Grok AI (xAI) any question, coding task, or team summary.",
    )
    @app_commands.describe(prompt="Your question, task, or prompt for Grok AI")
    async def grok(self, interaction: discord.Interaction, prompt: str) -> None:
        """Query Grok AI and return formatted embed response."""
        await interaction.response.defer(thinking=True)

        if not grok_service.is_configured:
            await interaction.followup.send(
                "⚠️ **Grok API Key Not Configured**\n"
                "Please set `GROK_API_KEY` in environment variables or Render dashboard.",
                ephemeral=True,
            )
            return

        try:
            system_instruction = (
                "You are Grok, an intelligent AI assistant integrated into the IITB Racing Team Discord bot. "
                "Provide clear, concise, well-formatted markdown answers."
            )
            answer = await grok_service.ask(prompt, system_prompt=system_instruction)

            # Format embed (Discord limits embed description to 4096 chars)
            display_answer = answer if len(answer) <= 3900 else answer[:3897] + "..."

            embed = discord.Embed(
                title="⚡ Grok AI Response",
                description=display_answer,
                color=discord.Color.blurple(),
            )
            embed.add_field(name="❓ Prompt", value=f"_{prompt[:500]}_", inline=False)
            embed.set_footer(
                text=f"xAI Grok • Model: {grok_service.model}",
                icon_url="https://x.ai/favicon.ico",
            )

            await interaction.followup.send(embed=embed)

        except PermissionError as pe:
            # 403 credit error
            await interaction.followup.send(
                f"{pe}\n\n*Note: Go to https://console.x.ai to add credits to your xAI team.*",
                ephemeral=True,
            )
        except Exception as e:
            logger.error("Error executing /grok command", error=str(e), prompt=prompt)
            await interaction.followup.send(
                f"⚠️ **Grok AI Error**: {e}",
                ephemeral=True,
            )

    @app_commands.command(
        name="ask",
        description="Ask Grok AI (xAI) any question.",
    )
    @app_commands.describe(question="Your question for Grok AI")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        """Alias slash command /ask -> calls grok implementation."""
        await self.grok(interaction, question)


async def setup(bot: commands.Bot) -> None:
    """Entry point for dynamic cog loading by DiscordSyncBot."""
    await bot.add_cog(GrokCog(bot))
    logger.info("GrokCog loaded successfully")

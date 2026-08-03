import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
import discord
from backend.modules.tasks.commands import TasksCog
from backend.models.core import Task, Channel, Project, AssigneeMapping
from tests.test_repositories import async_session

@pytest.mark.asyncio
async def test_work_report_command(async_session):
    # Setup mock bot
    bot = MagicMock()
    bot.db_session.return_value.__aenter__.return_value = async_session
    bot.db_session.return_value.__aexit__.return_value = None

    cog = TasksCog(bot)

    # Setup mock interaction
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild_id = "123456789"
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    # Invoke command
    await cog.work_report.callback(cog, interaction, status="Done", member=None, public=True)

    interaction.response.defer.assert_called_once_with(ephemeral=False)
    interaction.followup.send.assert_called_once()
    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Completed Work Report" in embed.title

@pytest.mark.asyncio
async def test_task_log_command(async_session):
    bot = MagicMock()
    bot.db_session.return_value.__aenter__.return_value = async_session
    bot.db_session.return_value.__aexit__.return_value = None

    cog = TasksCog(bot)

    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild_id = "123456789"
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.task_log.callback(cog, interaction, task_id="nonexistent-id")

    interaction.response.defer.assert_called_once_with(ephemeral=True)
    interaction.followup.send.assert_called_once()
    assert "not found" in interaction.followup.send.call_args.args[0]

@pytest.mark.asyncio
async def test_link_account_command(async_session):
    bot = MagicMock()
    bot.db_session.return_value.__aenter__.return_value = async_session
    bot.db_session.return_value.__aexit__.return_value = None

    from backend.modules.settings.commands import SettingsCog
    cog = SettingsCog(bot)

    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild_id = "123456789"
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    discord_user = MagicMock(spec=discord.Member)
    discord_user.id = "987654321"
    discord_user.display_name = "Narayana Malla"
    discord_user.mention = "<@987654321>"

    await cog.link_account.callback(cog, interaction, discord_user=discord_user, notion_name=None)

    interaction.response.defer.assert_called_once_with(ephemeral=True)
    interaction.followup.send.assert_called_once()
    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Linked" in embed.title


def test_parse_human_date_string():
    from backend.modules.tasks.commands import parse_human_date_string
    dt_today = parse_human_date_string("today")
    assert dt_today is not None

    dt_tomorrow = parse_human_date_string("tomorrow")
    assert dt_tomorrow is not None

    dt_iso = parse_human_date_string("2026-08-10")
    assert dt_iso is not None

    dt_invalid = parse_human_date_string("invalid-date-xyz")
    assert dt_invalid is None


import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
import discord
from backend.modules.tasks.commands import TasksCog
from backend.models.core import Task, Channel, Project, AssigneeMapping
from tests.test_repositories import async_session

@pytest.mark.asyncio
async def test_add_task_command(async_session):
    bot = MagicMock()
    bot.db_session.return_value.__aenter__.return_value = async_session
    bot.db_session.return_value.__aexit__.return_value = None

    cog = TasksCog(bot)

    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild_id = "123456789"
    interaction.channel_id = "channel-1"
    interaction.user = MagicMock()
    interaction.user.id = "user-123"
    interaction.user.display_name = "Narayana Malla"
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

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


@pytest.mark.asyncio
async def test_sync_members_command_particular_table(async_session):
    bot = MagicMock()
    bot.db_session.return_value.__aenter__.return_value = async_session
    bot.db_session.return_value.__aexit__.return_value = None

    from backend.modules.settings.commands import SettingsCog
    cog = SettingsCog(bot)

    guild = MagicMock(spec=discord.Guild)
    guild.id = "123456789"
    member = MagicMock(spec=discord.Member)
    member.id = "111222333"
    member.display_name = "Team Member 1"
    member.bot = False
    guild.members = [member]

    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.guild_id = "123456789"
    interaction.channel_id = "channel-particular"
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.sync_members.callback(cog, interaction, role=None, target_channel=None, all_databases=False)

    interaction.response.defer.assert_called_once_with(ephemeral=False)
    interaction.followup.send.assert_called_once()
    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Sync Completed" in embed.title


@pytest.mark.asyncio
async def test_sync_members_single_table_isolation(async_session, monkeypatch):
    from backend.models.core import Server, Project, Channel

    # Create server, project, and 2 mapped channels in DB
    server = Server(id="server-999", name="Test Server")
    async_session.add(server)
    await async_session.flush()

    project = Project(id=uuid.uuid4(), server_id="server-999", name="Test Project")
    async_session.add(project)
    await async_session.flush()

    ch1 = Channel(id="ch-table-1", project_id=project.id, notion_database_id="db-notion-111")
    ch2 = Channel(id="ch-table-2", project_id=project.id, notion_database_id="db-notion-222")
    async_session.add_all([ch1, ch2])
    await async_session.commit()

    bot = MagicMock()
    bot.db_session.return_value.__aenter__.return_value = async_session
    bot.db_session.return_value.__aexit__.return_value = None

    from backend.modules.settings.commands import SettingsCog
    cog = SettingsCog(bot)

    guild = MagicMock(spec=discord.Guild)
    guild.id = "server-999"
    member = MagicMock(spec=discord.Member)
    member.id = "user-777"
    member.display_name = "Alex Driver"
    member.bot = False
    guild.members = [member]

    # Mock NotionService.add_select_option_to_database
    called_db_ids = []
    async def mock_add_select_option(self, db_id, prop_name, opt_name):
        called_db_ids.append(db_id)
        return True


    monkeypatch.setattr("backend.services.notion_service.NotionService.add_select_option_to_database", mock_add_select_option)

    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.guild_id = "server-999"
    interaction.channel_id = "ch-table-1"  # Command run in channel 1
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    # Call sync_members with all_databases=False (default behavior)
    await cog.sync_members.callback(cog, interaction, role=None, target_channel=None, all_databases=False)

    # Verify option was added ONLY to db-notion-111, NOT db-notion-222
    assert "db-notion-111" in called_db_ids
    assert "db-notion-222" not in called_db_ids

    # Reset call tracker
    called_db_ids.clear()

    # Call sync_members with all_databases=True
    await cog.sync_members.callback(cog, interaction, role=None, target_channel=None, all_databases=True)

    # Verify options were added to BOTH databases when all_databases=True
    assert "db-notion-111" in called_db_ids
    assert "db-notion-222" in called_db_ids


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




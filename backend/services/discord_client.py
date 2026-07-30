import asyncio
import importlib
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import discord
from discord.ext import commands
from discord import app_commands
from backend.config.settings import settings
from backend.database.session import async_session_maker
import structlog

logger = structlog.get_logger(__name__)


class DiscordSyncBot(commands.Bot):
    """Custom discord.py Bot client orchestrating slash commands and module cogs."""

    def __init__(self) -> None:
        # Enable message content and member intents for thread monitoring and assigning
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix="!",  # Slash commands are primary, prefix prefix is fallback
            intents=intents,
            help_command=None,  # Disable default help, we will define custom slash help
            status=discord.Status.online,
            activity=discord.Activity(type=discord.ActivityType.watching, name="Notion Tasks ⚡"),
        )
        self.session_maker = async_session_maker

    @asynccontextmanager
    async def db_session(self) -> AsyncIterator[AsyncIterator]:
        """Async context manager providing a safe, isolated database session per command/event."""
        async with self.session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error("DB Session error during event/command lifecycle", error=str(e))
                raise
            finally:
                await session.close()

    async def setup_hook(self) -> None:
        """Invoked before the bot logs in. Dynamically registers all module cogs."""
        logger.info("Initializing bot setup hook...")
        await self._load_module_cogs()
        
        # In development, we can sync slash commands globally on start.
        # In production, we register them and sync them selectively or via settings to prevent rate limits.
        self.tree.on_error = self.on_app_command_error

    async def _load_module_cogs(self) -> None:
        """
        Walks backend/modules/ and dynamically loads all cog entry-points.

        Loads the following files from each module folder (if they exist):
          - commands.py  — slash command cogs
          - listener.py  — event listener cogs (on_message, on_reaction, etc.)

        This means adding a new module (e.g. inventory) only requires dropping
        a folder with a commands.py and/or listener.py — zero changes here.
        """
        modules_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "modules")

        if not os.path.exists(modules_dir):
            logger.warning(f"Modules directory not found: {modules_dir}")
            return

        # Ensure root directory is in sys.path to permit backend.* imports
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)

        # Files to auto-load from each module folder
        COG_ENTRY_POINTS = ("commands.py", "listener.py")

        for folder in sorted(os.listdir(modules_dir)):
            folder_path = os.path.join(modules_dir, folder)
            if not os.path.isdir(folder_path) or folder.startswith("__"):
                continue

            for entry_file in COG_ENTRY_POINTS:
                entry_path = os.path.join(folder_path, entry_file)
                if os.path.exists(entry_path):
                    entry_name = entry_file.replace(".py", "")
                    module_name = f"backend.modules.{folder}.{entry_name}"
                    try:
                        logger.info(f"Loading cog module: {module_name}")
                        await self.load_extension(module_name)
                    except Exception as e:
                        logger.error(
                            f"Failed to load cog module {module_name}",
                            error=str(e)
                        )

    async def on_ready(self) -> None:
        """Fires when gateway connection is established."""
        logger.info(
            "Bot connection established successfully",
            bot_user=str(self.user),
            bot_id=self.user.id
        )

        try:
            await self.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(type=discord.ActivityType.watching, name="Notion Tasks ⚡")
            )
        except Exception as pe:
            logger.warning("Failed to set bot presence", error=str(pe))
        
        # Start persistent scheduler and sync engine immediately
        try:
            from backend.scheduler.scheduler import ReminderScheduler
            if not hasattr(self, "scheduler") or not self.scheduler.scheduler.running:
                self.scheduler = ReminderScheduler(self)
                self.scheduler.start()
                await self.scheduler.reload_reminders_from_db()
                logger.info("Background Operations Scheduler loaded and running.")
        except Exception as e:
            logger.error("Failed to launch background Operations Scheduler", error=str(e))

        if not getattr(self, "_synced", False) and settings.ENV == "development":
            self._synced = True
            asyncio.create_task(self._async_sync_commands())

    async def _async_sync_commands(self) -> None:
        """Background task to sync slash commands without delaying gateway/scheduler startup."""
        logger.info("Development mode detected. Syncing slash commands in background...")
        try:
            for guild in self.guilds:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info("Slash commands synced to guild", guild=guild.name, command_count=len(synced))
        except Exception as e:
            logger.error("Failed to sync commands tree", error=str(e))

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Global interaction listener to process persistent task card button clicks."""
        custom_id = interaction.data.get("custom_id") if interaction.data else None
        if not custom_id or not isinstance(custom_id, str):
            return

        if custom_id.startswith("op_"):
            parts = custom_id.split(":", 1)
            if len(parts) == 2:
                action_prefix, task_id_str = parts
                action = action_prefix[3:]  # strip 'op_'
                try:
                    from backend.modules.tasks.interactions import handle_task_interaction
                    await handle_task_interaction(interaction, self, action, task_id_str)
                except Exception as e:
                    logger.error("Failed to handle persistent task interaction", custom_id=custom_id, error=str(e))
                    if not interaction.response.is_done():
                        await interaction.response.send_message("An error occurred processing this action.", ephemeral=True)
                    else:
                        await interaction.followup.send("An error occurred processing this action.", ephemeral=True)

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Global app command error handler."""
        from backend.utils.permissions import OperationsUnauthorizedError

        if isinstance(error, OperationsUnauthorizedError):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description=(
                        f"You do not possess the operations authority required to run this command.\n\n"
                        f"**Required Level**: `{error.required_role}`\n"
                        f"**Your Roles**: {', '.join([f'`{r}`' for r in error.user_roles if r != '@everyone']) or 'None'}"
                    ),
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
        elif isinstance(error, app_commands.errors.MissingRole):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description=f"You do not possess the required role to run this: `{error.missing_role}`.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
        elif isinstance(error, app_commands.errors.MissingPermissions):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="You do not have administrative permissions to run this command.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
        else:
            logger.error("App command error occurred", error=str(error))
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred while executing this command. Please contact the Operations Lead.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "An error occurred while processing your request.",
                    ephemeral=True
                )


# Bot instance singleton
bot = DiscordSyncBot()

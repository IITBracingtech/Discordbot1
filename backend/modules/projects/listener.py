import discord
from discord.ext import commands
from sqlalchemy import select
from backend.models.core import Server
import structlog

logger = structlog.get_logger(__name__)


class ProjectsListenerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Automatically registers the new Discord server in PostgreSQL on bot join."""
        logger.info("Bot joined a new Discord server", server_id=str(guild.id), server_name=guild.name)
        async with self.bot.db_session() as session:
            res = await session.execute(select(Server).where(Server.id == str(guild.id)))
            server = res.scalar_one_or_none()
            if not server:
                server = Server(id=str(guild.id), name=guild.name)
                session.add(server)
                await session.commit()
                logger.info("Registered new Server in database", server_id=str(guild.id))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProjectsListenerCog(bot))

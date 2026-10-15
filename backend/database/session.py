from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.config.settings import settings
import structlog

logger = structlog.get_logger(__name__)

# Configure the async database engine.
# pool_pre_ping=True  — validates connection before use, discards stale ones.
# pool_recycle=300    — recycles connections every 5 min to prevent Supabase pgBouncer
#                       from dropping them silently (which causes empty-message InterfaceErrors).
# pool_size=5         — lower count since Supabase free tier has a hard connection cap.
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Never echo SQL in production — too noisy
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=5,
    max_overflow=5,
    pool_timeout=30,
    connect_args={"statement_cache_size": 0, "server_settings": {"application_name": "RaceControlBot"}},
)

# Async session factory
async_session_maker = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for obtaining async database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception as e:
            logger.error("Database session error", error=str(e))
            await session.rollback()
            raise
        finally:
            await session.close()

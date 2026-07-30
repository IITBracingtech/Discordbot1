from functools import wraps
from typing import Callable, TypeVar
import discord
from discord import app_commands
from backend.modules.settings.repository import SettingRepository
import structlog

logger = structlog.get_logger(__name__)

# Roles in order of ascending authority
ROLE_HIERARCHY = {
    "Member": 1,
    "Lead": 2,
    "Manager": 3,
    "Admin": 4
}


class OperationsUnauthorizedError(app_commands.AppCommandError):
    """Exception raised when a user does not meet role requirements for operations commands."""
    
    def __init__(self, required_role: str, user_roles: list[str]) -> None:
        self.required_role = required_role
        self.user_roles = user_roles
        super().__init__(f"Operation requires role authority level: '{required_role}'.")


def check_role_hierarchy(user_role_level: str, required_role: str) -> bool:
    """Compare role hierarchy to see if user has sufficient authority."""
    user_val = ROLE_HIERARCHY.get(user_role_level, 0)
    req_val = ROLE_HIERARCHY.get(required_role, 0)
    return user_val >= req_val


def has_operation_role(required_role: str) -> Callable:
    """Decorator to enforce platform operation roles on slash commands.
    
    Enforces that a user has a role configured in Supabase settings
    or has a Discord role with the matching name. Guild administrators bypass.
    """

    async def predicate(interaction: discord.Interaction) -> bool:
        # Guild administrator bypass
        if interaction.permissions and interaction.permissions.administrator:
            return True

        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            raise app_commands.NoPrivateMessage("This command can only be used within servers.")

        member: discord.Member = interaction.user
        guild_id = str(interaction.guild.id)
        bot = interaction.client

        # Get settings from DB session
        async with bot.db_session() as session:
            settings_repo = SettingRepository(session)
            
            # Map role settings keys
            role_key = f"role_{required_role.lower()}_id"
            db_setting = await settings_repo.get_by_key(guild_id, role_key)
            configured_role_id = db_setting.value if db_setting else None

            # Get admin role too (admin overrides all)
            db_admin = await settings_repo.get_by_key(guild_id, "role_admin_id")
            admin_role_id = db_admin.value if db_admin else None

        # Build set of role IDs and names the user holds
        user_role_ids = {str(r.id) for r in member.roles}
        user_role_names = {r.name.lower() for r in member.roles}

        # 1. Check database-mapped roles
        if configured_role_id and configured_role_id in user_role_ids:
            return True
        if admin_role_id and admin_role_id in user_role_ids:
            return True

        # 2. Fallback: Check role names (case-insensitive matches: e.g., 'lead' or 'operations lead')
        for role_name, level in ROLE_HIERARCHY.items():
            # If the user has a role name containing the hierarchy role
            has_role_name = any(role_name.lower() in r_name for r_name in user_role_names)
            
            # Check if this role level matches or exceeds the required level
            if has_role_name and check_role_hierarchy(role_name, required_role):
                return True

        # No match found, raise exception for the global handler
        raise OperationsUnauthorizedError(required_role, [r.name for r in member.roles])

    return app_commands.check(predicate)

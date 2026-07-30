import uuid
from datetime import datetime, timezone, timedelta
from typing import Any
import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update, and_
from sqlalchemy.orm import selectinload
from backend.database.session import async_session_maker
from backend.models.core import Task, Reminder, AssigneeMapping
from backend.modules.settings.repository import ReminderRepository
from backend.modules.tasks.repository import TaskRepository
from zoneinfo import ZoneInfo
import structlog

logger = structlog.get_logger(__name__)

# Global AsyncIOScheduler instance
scheduler = AsyncIOScheduler(timezone=ZoneInfo("Asia/Kolkata"))


async def send_task_reminder(reminder_id: str, bot: discord.Client) -> None:
    """Invoked when a scheduled reminder job fires. Mentions assignee in the task thread."""
    logger.info("Reminder job triggered", reminder_id=reminder_id)
    
    async with bot.db_session() as session:
        reminder_repo = ReminderRepository(session)
        task_repo = TaskRepository(session)

        reminder = await reminder_repo.get_by_id(uuid.UUID(reminder_id))
        if not reminder or reminder.status != "SCHEDULED":
            return

        # Fetch task details
        task = await task_repo.get_by_id(reminder.task_id)
        if not task or task.status in ["Done", "Completed"]:
            # Task is already completed, cancel reminder execution
            reminder.status = "CANCELLED"
            await session.flush()
            return

        # Resolve mention if user mapped
        assignee_mention = ""
        if task.assignee:
            assignee_mention = f"<@{task.assignee.discord_user_id}> "

        # Try sending to task discussion thread
        thread_id = task.thread_mapping.discord_thread_id if task.thread_mapping else None
        if thread_id:
            try:
                thread = bot.get_channel(int(thread_id))
                if thread and isinstance(thread, (discord.Thread, discord.TextChannel)):
                    from backend.modules.tasks.embeds import create_reminder_embed
                    embed = create_reminder_embed(
                        task,
                        reminder.reminder_type,
                        assignee_mention if assignee_mention else None,
                    )
                    await thread.send(content=f"{assignee_mention}" if assignee_mention else "", embed=embed)
                    reminder.status = "SENT"
                    logger.info("Sent task reminder successfully", task_id=str(task.id), reminder_type=reminder.reminder_type)
            except Exception as e:
                logger.error("Failed to send reminder message to Discord thread", thread_id=thread_id, error=str(e))
                reminder.status = "FAILED"
        else:
            logger.warning("No Discord thread mapped to task, skipping reminder dispatch", task_id=str(task.id))
            reminder.status = "FAILED"

        await session.flush()


async def check_overdue_tasks_9am(bot: discord.Client) -> None:
    """Recurring cron job triggered every morning at 9 AM IST. Escalates overdue tasks."""
    logger.info("Starting morning 9 AM IST overdue task sweep and escalation...")

    now = datetime.now(timezone.utc)
    async with bot.db_session() as session:
        # Fetch tasks that are past their due date and not completed
        query = select(Task).where(
            and_(
                Task.due_date < now,
                Task.status.notin_(["Done", "Completed"])
            )
        ).options(
            selectinload(Task.thread_mapping),
            selectinload(Task.message_mapping),
            selectinload(Task.assignee),
            selectinload(Task.channel).selectinload(Channel.project)
        )
        result = await session.execute(query)
        overdue_tasks = result.scalars().all()

        for task in overdue_tasks:
            # Determine target chat locations
            channel_id = task.channel_id
            msg_id = task.message_mapping.discord_message_id if task.message_mapping else None
            thread_id = task.thread_mapping.discord_thread_id if task.thread_mapping else None

            # Calculate overdue duration
            overdue_duration = now - task.due_date
            days_overdue = overdue_duration.days

            assignee_mention = f"<@{task.assignee.discord_user_id}>" if task.assignee else "Unassigned"

            # Fetch creator's details from Notion page dynamically
            creator_mention = None
            try:
                from backend.services.notion_service import NotionService
                ns = NotionService()
                page = await ns.retrieve_page(task.notion_page_id)
                creator_id = page.get("created_by", {}).get("id")
                if creator_id:
                    from backend.modules.settings.repository import AssigneeMappingRepository
                    ar = AssigneeMappingRepository(session)
                    mapping = await ar.get_by_notion_user_id(task.channel.project.server_id, creator_id)
                    if mapping:
                        creator_mention = f"<@{mapping.discord_user_id}>"
                    else:
                        creator_name = await ns.get_user_name(creator_id)
                        creator_mention = f"**{creator_name}**"
            except Exception as e:
                logger.error("Failed to fetch page creator details for escalation", task_id=str(task.id), error=str(e))

            # Fetch manager role ID for Day 3 escalation
            manager_mention = None
            try:
                from backend.modules.settings.repository import SettingRepository
                sr = SettingRepository(session)
                db_manager = await sr.get_by_key(task.channel.project.server_id, "role_manager_id")
                if db_manager:
                    manager_mention = f"<@&{db_manager.value}>"
            except Exception:
                pass

            if not manager_mention:
                manager_mention = "@here"

            # Build alert message based on overdue level
            if days_overdue == 0:
                # Day 1 Overdue: Notify Member
                alert_text = (
                    f"⚠️ **TASK OVERDUE (Day 1)**\n"
                    f"{assignee_mention}, the task **{task.title}** is past its deadline. Please post a progress update or click complete."
                )
            elif days_overdue == 1:
                # Day 2 Overdue: Notify CT
                ct_display = creator_mention if creator_mention else "CT Lead"
                alert_text = (
                    f"⚠️ **TASK OVERDUE (Day 2)**\n"
                    f"{assignee_mention}, the task **{task.title}** is now 2 days overdue!\n"
                    f"CC: {ct_display}"
                )
            else:
                # Day 3+ Overdue: Notify Manager
                ct_display = creator_mention if creator_mention else "CT Lead"
                alert_text = (
                    f"🚨 **TASK ESCALATION (Day 3+)**\n"
                    f"{assignee_mention}, the task **{task.title}** is {days_overdue + 1} days overdue!\n"
                    f"CC: {ct_display} {manager_mention}"
                )

            # Send alert to thread if available, else reply to task card message
            try:
                thread = bot.get_channel(int(thread_id)) if thread_id else None
                if thread and isinstance(thread, (discord.Thread, discord.TextChannel)):
                    await thread.send(content=alert_text)
                    logger.info("Sent overdue alert to task thread", task_id=str(task.id), days_overdue=days_overdue)
                else:
                    # Reply to the task card message in the channel
                    channel = bot.get_channel(int(channel_id))
                    if channel and isinstance(channel, discord.TextChannel) and msg_id:
                        message = await channel.fetch_message(int(msg_id))
                        await message.reply(content=alert_text, mention_author=True)
                        logger.info("Sent overdue alert to task card message reply", task_id=str(task.id), days_overdue=days_overdue)
            except Exception as e:
                logger.error("Failed to dispatch overdue alert", task_id=str(task.id), error=str(e))


async def cleanup_completed_threads_24h(bot: discord.Client) -> None:
    """Sweeps tasks completed > 24 hours ago and deletes their archived Discord discussion threads."""
    logger.info("Running 24h completed thread cleanup sweep...")
    now = datetime.now(timezone.utc)
    twenty_four_hours_ago = now - timedelta(hours=24)

    async with bot.db_session() as session:
        query = (
            select(Task)
            .where(
                and_(
                    Task.status.in_(["Done", "Completed"]),
                    Task.completed_time <= twenty_four_hours_ago
                )
            )
            .options(selectinload(Task.thread_mapping))
        )
        result = await session.execute(query)
        completed_tasks = result.scalars().all()

        deleted_count = 0
        for task in completed_tasks:
            if task.thread_mapping and task.thread_mapping.discord_thread_id:
                thread_id_str = task.thread_mapping.discord_thread_id
                try:
                    thread = bot.get_channel(int(thread_id_str))
                    if not thread:
                        try:
                            thread = await bot.fetch_channel(int(thread_id_str))
                        except Exception:
                            thread = None

                    if thread and isinstance(thread, (discord.Thread, discord.TextChannel)):
                        await thread.delete()
                        logger.info("Deleted archived discussion thread 24h post-completion", task_id=str(task.id), thread_id=thread_id_str)
                        deleted_count += 1
                except discord.NotFound:
                    logger.info("Archived thread already deleted from Discord", thread_id=thread_id_str)
                except Exception as e:
                    logger.error("Failed to delete archived thread", thread_id=thread_id_str, error=str(e))

                await session.delete(task.thread_mapping)

        await session.flush()
        if deleted_count > 0:
            logger.info("Completed 24h thread cleanup sweep", deleted_threads=deleted_count)


class ReminderScheduler:
    """Coordinator handling persistent task reminder scheduling and reloads."""

    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot
        self.scheduler = scheduler

    def start(self) -> None:
        """Starts the background scheduler and registers recurring reports/sweeps."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("APScheduler engine started successfully.")
            
            # Register morning 9 AM IST overdue job
            self.scheduler.add_job(
                check_overdue_tasks_9am,
                trigger="cron",
                hour=9,
                minute=0,
                args=[self.bot],
                id="daily_overdue_check_9am",
                replace_existing=True
            )
            
            # Register morning 9 AM IST operations briefing
            self.scheduler.add_job(
                self._dispatch_morning_briefing,
                trigger="cron",
                hour=9,
                minute=0,
                id="daily_morning_briefing_9am",
                replace_existing=True
            )
            
            # Register evening 7 PM IST operations debriefing
            self.scheduler.add_job(
                self._dispatch_evening_briefing,
                trigger="cron",
                hour=19,
                minute=0,
                id="daily_evening_briefing_7pm",
                replace_existing=True
            )
            
            # Register weekly Sunday 9 AM IST review report
            self.scheduler.add_job(
                self._dispatch_weekly_report,
                trigger="cron",
                day_of_week="sun",
                hour=9,
                minute=0,
                id="weekly_analytics_report_9am",
                replace_existing=True
            )

            # Register monthly 1st 9 AM IST report
            self.scheduler.add_job(
                self._dispatch_monthly_report,
                trigger="cron",
                day=1,
                hour=9,
                minute=0,
                id="monthly_analytics_report_9am",
                replace_existing=True
            )

            # Register periodic sync sweep (pull changes from Notion every 30 seconds)
            self.scheduler.add_job(
                run_periodic_sync,
                trigger="interval",
                seconds=30,
                args=[self.bot],
                id="periodic_sync_sweep_30s",
                replace_existing=True
            )

            # Register periodic 24h completed thread cleanup sweep (runs every 30 minutes)
            self.scheduler.add_job(
                cleanup_completed_threads_24h,
                trigger="interval",
                minutes=30,
                args=[self.bot],
                id="completed_thread_cleanup_24h",
                replace_existing=True
            )
            
            logger.info("Daily Overdue, reports briefings, 30s Notion sync, and 24h thread cleanup jobs registered.")

    async def _dispatch_morning_briefing(self) -> None:
        from backend.services.notification_service import NotificationService
        ns = NotificationService(self.bot)
        await ns.dispatch_daily_briefings("MORNING")

    async def _dispatch_evening_briefing(self) -> None:
        from backend.services.notification_service import NotificationService
        ns = NotificationService(self.bot)
        await ns.dispatch_daily_briefings("EVENING")

    async def _dispatch_weekly_report(self) -> None:
        from backend.services.analytics_service import AnalyticsService
        svc = AnalyticsService(self.bot)
        await svc.dispatch_weekly_reports()

    async def _dispatch_monthly_report(self) -> None:
        from backend.services.analytics_service import AnalyticsService
        svc = AnalyticsService(self.bot)
        await svc.dispatch_monthly_reports()

    async def reload_reminders_from_db(self) -> None:
        """Queries active scheduled reminders from database and re-seeds APScheduler jobs."""
        logger.info("Reloading reminders from database...")
        
        async with self.bot.db_session() as session:
            reminder_repo = ReminderRepository(session)
            active_reminders = await reminder_repo.get_active_scheduled_reminders()

        reload_count = 0
        now = datetime.now(timezone.utc)
        for r in active_reminders:
            # If trigger time is in the future, re-schedule it
            if r.trigger_time > now:
                # Remove if exists to prevent duplicates
                try:
                    if self.scheduler.get_job(str(r.id)):
                        self.scheduler.remove_job(str(r.id))
                except Exception:
                    pass
                
                self.scheduler.add_job(
                    send_task_reminder,
                    trigger="date",
                    run_date=r.trigger_time.astimezone(ZoneInfo("Asia/Kolkata")),
                    args=[str(r.id), self.bot],
                    id=str(r.id)
                )
                reload_count += 1
            else:
                # Trigger time is in the past and status is SCHEDULED, execute or mark expired
                logger.warning("Found expired scheduled reminder in DB on reload, skipping", reminder_id=str(r.id))

        logger.info("Reminders reloaded from database", scheduled_count=reload_count)

    async def schedule_task_reminders(self, task: Task, session: AsyncSession) -> None:
        """Calculates and registers task deadline reminder intervals inside DB and APScheduler."""
        if not task.due_date:
            return

        due_date = task.due_date
        if due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=timezone.utc)

        # 1. Clear any existing scheduled/sent reminders for this task
        reminder_repo = ReminderRepository(session)
        existing = await reminder_repo.get_by_task_id(task.id)
        for r in existing:
            # Cancel job in memory
            try:
                if self.scheduler.get_job(str(r.id)):
                    self.scheduler.remove_job(str(r.id))
            except Exception:
                pass
            r.status = "CANCELLED"

        # 2. Define intervals before deadline
        intervals = [
            ("3_DAYS",  timedelta(days=3)),
            ("1_DAY",   timedelta(days=1)),
            ("6_HOURS", timedelta(hours=6)),
            ("1_HOUR",  timedelta(hours=1)),
            ("15_MIN",  timedelta(minutes=15)),
            ("DEADLINE", timedelta(seconds=0)),
        ]

        now = datetime.now(timezone.utc)
        scheduled_jobs = 0

        for r_type, delta in intervals:
            trigger_time = due_date - delta
            if trigger_time > now:
                # Record in database
                reminder = Reminder(
                    task_id=task.id,
                    trigger_time=trigger_time,
                    reminder_type=r_type,
                    status="SCHEDULED"
                )
                session.add(reminder)
                await session.flush() # Generates UUID for reminder.id

                # Add to scheduler in-memory
                self.scheduler.add_job(
                    send_task_reminder,
                    trigger="date",
                    run_date=trigger_time.astimezone(ZoneInfo("Asia/Kolkata")),
                    args=[str(reminder.id), self.bot],
                    id=str(reminder.id)
                )
                scheduled_jobs += 1

        logger.info("Scheduled deadline reminders for task", task_id=str(task.id), job_count=scheduled_jobs)


async def run_periodic_sync(bot: discord.Client) -> None:
    """Helper job invoking the SyncEngine to poll all registered channels."""
    from backend.sync.sync_engine import SyncEngine
    sync = SyncEngine(bot)
    await sync.sync_all_channels()

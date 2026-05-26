import logging
from datetime import time as dtime
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

from ai_social_content_generator.telegram_bot.users import (
    get_reminder_schedule,
    iter_all_users,
)

logger = logging.getLogger(__name__)

JERUSALEM_TZ = ZoneInfo("Asia/Jerusalem")
SLOT_TIMES = {
    "morning": dtime(9, 0, tzinfo=JERUSALEM_TZ),
    "evening": dtime(18, 0, tzinfo=JERUSALEM_TZ),
}
REMINDER_TEXT = "Time to post! Open the bot to create something."
JOB_NAME_PREFIX = "reminder_"


def job_name_for_user(user_id: int) -> str:
    """Each user has at most one reminder job, named deterministically
    so we can find/remove it later."""
    return f"{JOB_NAME_PREFIX}{user_id}"


async def send_reminder_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback. Sends the daily reminder text to one user.
    user_id is passed via context.job.data."""
    user_id = context.job.data
    try:
        await context.bot.send_message(chat_id=user_id, text=REMINDER_TEXT)
        logger.info("Sent daily reminder to user_id=%s", user_id)
    except Exception as e:
        logger.warning(
            "Failed to send reminder to user_id=%s: %s", user_id, e,
        )


def schedule_reminder_for_user(
    application: Application,
    user_id: int,
    slot: str,
) -> None:
    """(Re)schedule a daily reminder for one user at the given slot.
    Removes any existing job for this user before creating a new one."""
    if slot not in SLOT_TIMES:
        raise ValueError(f"Invalid slot: {slot!r}")

    cancel_reminder_for_user(application, user_id)

    job_queue = application.job_queue
    if job_queue is None:
        logger.error(
            "JobQueue is None. Did you install python-telegram-bot with "
            "[job-queue] extra?"
        )
        return

    job_queue.run_daily(
        callback=send_reminder_callback,
        time=SLOT_TIMES[slot],
        data=user_id,
        name=job_name_for_user(user_id),
    )
    logger.info(
        "Scheduled %s reminder for user_id=%s at %s",
        slot, user_id, SLOT_TIMES[slot],
    )


def cancel_reminder_for_user(
    application: Application,
    user_id: int,
) -> int:
    """Cancel any existing reminder job for this user. Returns count
    of jobs removed."""
    job_queue = application.job_queue
    if job_queue is None:
        return 0
    name = job_name_for_user(user_id)
    jobs = job_queue.get_jobs_by_name(name)
    for job in jobs:
        job.schedule_removal()
    if jobs:
        logger.info(
            "Cancelled %d reminder job(s) for user_id=%s",
            len(jobs), user_id,
        )
    return len(jobs)


async def rebuild_all_reminders_on_startup(application: Application) -> None:
    """Called once at bot startup. Iterates over all users and
    schedules reminders for those who have enabled them."""
    logger.info("Rebuilding reminder schedules from vault...")
    count = 0
    for user_id, user_data in iter_all_users():
        schedule = get_reminder_schedule(user_data)
        if schedule.get("enabled") and schedule.get("slot") in SLOT_TIMES:
            schedule_reminder_for_user(
                application, user_id, schedule["slot"],
            )
            count += 1
    logger.info("Rebuilt %d reminder schedule(s) on startup", count)

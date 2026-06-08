"""Daily token-refresh job. Long-lived IG tokens last ~60 days; we
refresh any token within 7 days of expiry. On hard failure (revoked /
401) we clear the token and try to nudge the user to reconnect.

Plumbed through the bot's APScheduler-backed JobQueue, mirroring
rebuild_all_reminders_on_startup's walk pattern."""

import logging
from datetime import time as dtime
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

from ai_social_content_generator.instagram.oauth import OAuthError, refresh_long_token
from ai_social_content_generator.instagram.token_store import (
    clear_token,
    get_token,
    is_expired_or_soon,
    save_token,
)
from ai_social_content_generator.telegram_bot.users import iter_all_users

logger = logging.getLogger(__name__)

JERUSALEM_TZ = ZoneInfo("Asia/Jerusalem")
REFRESH_TIME = dtime(4, 0, tzinfo=JERUSALEM_TZ)
JOB_NAME = "instagram_token_refresh"
WITHIN_DAYS = 7


async def _refresh_one_user(application: Application, user_id: int) -> None:
    """Refresh one user's token. On 401-class failure, clear and notify."""
    stored = get_token(user_id)
    if not stored:
        return
    try:
        payload = await refresh_long_token(stored["token"])
    except OAuthError as e:
        logger.warning(
            "Token refresh failed for user_id=%s, clearing: %s", user_id, e,
        )
        clear_token(user_id)
        try:
            await application.bot.send_message(
                chat_id=user_id,
                text=(
                    "📷 Your Instagram connection expired. Open Settings → "
                    "Connect Instagram to reconnect."
                ),
            )
        except Exception:
            logger.exception(
                "Failed to notify user_id=%s about expired Instagram", user_id,
            )
        return

    save_token(
        user_id=user_id,
        token=payload["access_token"],
        expires_in=int(payload["expires_in"]),
        ig_account_id=stored.get("ig_account_id", ""),
    )


async def refresh_all_tokens_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue daily callback. Walks every user, refreshes those whose
    token expires within WITHIN_DAYS."""
    logger.info("Running Instagram token refresh sweep")
    refreshed = 0
    cleared = 0
    for user_id, _ in iter_all_users():
        if not is_expired_or_soon(user_id, within_days=WITHIN_DAYS):
            continue
        before = bool(get_token(user_id))
        await _refresh_one_user(context.application, user_id)
        after = bool(get_token(user_id))
        if after:
            refreshed += 1
        elif before:
            cleared += 1
    logger.info(
        "Instagram token refresh sweep done: refreshed=%d cleared=%d",
        refreshed, cleared,
    )


def schedule_token_refresh_job(application: Application) -> None:
    """Register the daily refresh job. Idempotent — removes any existing
    job with the same name first."""
    job_queue = application.job_queue
    if job_queue is None:
        logger.error(
            "JobQueue is None — install python-telegram-bot with [job-queue]."
        )
        return
    for existing in job_queue.get_jobs_by_name(JOB_NAME):
        existing.schedule_removal()
    job_queue.run_daily(
        callback=refresh_all_tokens_callback,
        time=REFRESH_TIME,
        name=JOB_NAME,
    )
    logger.info("Scheduled Instagram token refresh daily at %s", REFRESH_TIME)

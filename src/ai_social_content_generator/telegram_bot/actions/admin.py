import asyncio
import logging
import os
import time
from datetime import timedelta

from telegram import Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_admin
from ai_social_content_generator.telegram_bot.users import iter_all_users

logger = logging.getLogger(__name__)


_BOT_START_TIME: float | None = None


def set_bot_start_time(start_time: float) -> None:
    """Called by bot.py exactly once at startup."""
    global _BOT_START_TIME
    _BOT_START_TIME = start_time


def _format_uptime(seconds: float) -> str:
    """Convert uptime seconds to a readable string."""
    delta = timedelta(seconds=int(seconds))
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes, seconds_left = divmod(rem, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds_left or not parts:
        parts.append(f"{seconds_left}s")
    return " ".join(parts)


@require_admin
async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """/status — show bot uptime since last process start."""
    if _BOT_START_TIME is None:
        await update.message.reply_text("Uptime unavailable (startup time not set).")
        return

    uptime_seconds = time.time() - _BOT_START_TIME
    uptime_str = _format_uptime(uptime_seconds)
    user_count = sum(1 for _ in iter_all_users())

    text = (
        f"🤖 Bot Status\n\n"
        f"Uptime: {uptime_str}\n"
        f"Users: {user_count}\n"
        f"PID: {os.getpid()}"
    )
    await update.message.reply_text(text)


@require_admin
async def broadcast_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """/broadcast <message> — send <message> to every known user."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /broadcast <message>\n\n"
            "Example: /broadcast New feature shipped!"
        )
        return

    message = " ".join(context.args).strip()
    if not message:
        await update.message.reply_text("Message cannot be empty.")
        return

    admin_user_id = update.effective_user.id
    all_users = list(iter_all_users())

    if not all_users:
        await update.message.reply_text("No users to broadcast to.")
        return

    await update.message.reply_text(
        f"📢 Broadcasting to {len(all_users)} user(s)..."
    )

    sent = 0
    failed = 0
    failed_user_ids: list[int] = []

    for user_id, _user_data in all_users:
        if user_id == admin_user_id:
            continue
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            sent += 1
        except Exception as e:
            failed += 1
            failed_user_ids.append(user_id)
            logger.warning(
                "Broadcast failed for user_id=%s: %s", user_id, e,
            )
        # ~30 msg/sec is the hard cap; 50ms = 20/sec, comfortable margin.
        await asyncio.sleep(0.05)

    summary = f"✅ Broadcast complete\n\nSent: {sent}\nFailed: {failed}"
    if failed_user_ids:
        sample = failed_user_ids[:5]
        suffix = f" (+{len(failed_user_ids) - 5} more)" if len(failed_user_ids) > 5 else ""
        summary += f"\nFailed IDs: {sample}{suffix}"

    await update.message.reply_text(summary)
    logger.info(
        "Broadcast by admin=%s: sent=%d, failed=%d",
        admin_user_id, sent, failed,
    )


@require_admin
async def restart_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """/restart — exit the process cleanly. systemd respawns via
    Restart=always (configured in infra/ai-social-bot.service)."""
    await update.message.reply_text(
        "🔄 Restarting bot. Should be back in a few seconds."
    )

    logger.info(
        "Restart requested by admin=%s. Exiting now; systemd will respawn.",
        update.effective_user.id,
    )

    # Give Telegram time to deliver the confirmation message before exit.
    await asyncio.sleep(1.0)

    # os._exit instead of sys.exit: sys.exit raises SystemExit which the
    # polling loop may catch and swallow, preventing systemd respawn.
    os._exit(0)

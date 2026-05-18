import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import load_user, save_user
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.actions.profile_skill_creator import (
    build_prompt_with_bio,
    build_engagement_digest,
    _parse_analysis_json,
    _save_analysis,
)
from ai_social_content_generator.ingestion.instagram_scraper import get_profile

logger = logging.getLogger(__name__)

COMPETITOR_CAP = 10
WAITING_FOR_COMPETITOR_HANDLE = 100


def remove_competitor(user_id: int, index: int) -> str | None:
    """Pops the competitor at index from the user vault and deletes
    their cache files. Returns the removed handle, or None if the
    user has no vault or the index is out of range."""
    user_data = load_user(user_id)
    if user_data is None:
        return None
    competitors = user_data.get("competitors", [])
    if not (0 <= index < len(competitors)):
        return None

    removed_handle = competitors.pop(index)
    save_user(user_id, user_data)

    for suffix in ("analysis", "profile", "posts"):
        cache_path = Path(f"cache/{removed_handle}-{suffix}.json")
        if cache_path.exists():
            cache_path.unlink()

    return removed_handle


@require_auth
async def competitor_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user_data = load_user(user_id)
    competitors = user_data.get("competitors", []) if user_data else []

    if len(competitors) >= COMPETITOR_CAP:
        await query.edit_message_text(
            f"You have {COMPETITOR_CAP} competitors (max). Remove one first."
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "Send the Instagram handle (e.g., @nasa or nasa):"
    )
    return WAITING_FOR_COMPETITOR_HANDLE


async def competitor_receive_handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    handle = update.message.text.lstrip("@").strip().lower()

    user_data = load_user(user_id)
    if user_data is None:
        await update.message.reply_text("No account info. Please complete onboarding first.")
        return ConversationHandler.END

    competitors = user_data.get("competitors", [])

    if handle in competitors:
        await update.message.reply_text(f"@{handle} is already in your list.")
        return ConversationHandler.END

    if len(competitors) >= COMPETITOR_CAP:
        await update.message.reply_text("At the limit, remove one first.")
        return ConversationHandler.END

    await update.message.reply_text(f"Adding @{handle}, takes about a minute...")

    profile = get_profile(handle, limit=20)
    if profile is None:
        await update.message.reply_text(f"Couldn't find @{handle}, check spelling")
        return ConversationHandler.END

    profile_data = Path(f"cache/{handle}-profile.json").read_text(encoding="utf-8")
    posts_data = Path(f"cache/{handle}-posts.json").read_text(encoding="utf-8")

    posts_list = json.loads(posts_data)
    engagement_digest = build_engagement_digest(posts_list, top_n=3)
    prompt = build_prompt_with_bio(handle, profile_data, engagement_digest)

    claude_reply = message_claude(prompt)
    raw_output = getattr(claude_reply, "stdout", None)
    returncode = getattr(claude_reply, "returncode", -1)

    if not raw_output or returncode != 0:
        logger.error("Claude failed for competitor handle=%s reply=%r", handle, claude_reply)
        await update.message.reply_text(f"Failed to analyze @{handle}, try again later")
        return ConversationHandler.END

    analysis = _parse_analysis_json(raw_output)
    if analysis is None:
        logger.error("Failed to parse Claude JSON for competitor handle=%s raw=%s", handle, raw_output)
        await update.message.reply_text(f"Failed to analyze @{handle}, try again later")
        return ConversationHandler.END

    analysis["handle"] = handle
    analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    _save_analysis(handle, analysis)

    user_data["competitors"].append(handle)
    save_user(user_id, user_data)

    await update.message.reply_text(f"✓ Added @{handle}")
    return ConversationHandler.END

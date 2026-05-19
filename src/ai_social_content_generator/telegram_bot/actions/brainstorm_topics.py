import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import load_user, save_user, add_topic
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.actions.compose_carousel import build_competitor_section
from ai_social_content_generator.telegram_bot.actions.profile_skill_creator import build_engagement_digest

logger = logging.getLogger(__name__)

SKILL_PATH = Path("src/ai_social_content_generator/brainstorm_topics/SKILL.md")
MAX_MESSAGE_LEN = 4000
MIN_PARSED_TOPICS = 5


@require_auth
async def brainstorm_topics_from_vault(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = update.effective_user.id

    await query.edit_message_text("Brainstorming, ~30 sec...")

    user_data = load_user(user_id)

    if user_data is None or "handle" not in user_data or "niche" not in user_data:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No account info. Please complete onboarding first.",
        )
        return

    handle = user_data["handle"]

    analysis_path = Path(f"cache/{handle}-analysis.json")
    if not analysis_path.exists():
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please run Analyze first before brainstorming topics.",
        )
        return

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))

    posts_path = Path(f"cache/{handle}-posts.json")
    posts_list = json.loads(posts_path.read_text(encoding="utf-8")) if posts_path.exists() else []
    engagement_digest = build_engagement_digest(posts_list, top_n=3)

    competitors = user_data.get("competitors", [])
    competitor_section = build_competitor_section(competitors)

    niche = analysis.get("niche") or user_data.get("niche", "")
    voice = analysis.get("voice", [])
    themes = analysis.get("recurring_themes", [])

    voice_str = ", ".join(voice) if isinstance(voice, list) else str(voice)

    if isinstance(themes, list):
        themes_str = "\n".join(f"- {t}" for t in themes)
    else:
        themes_str = str(themes)

    existing_topics = user_data.get("topics", [])
    if not existing_topics:
        existing_topics_str = "(none yet)"
    else:
        existing_topics_str = "\n".join(
            f"{i + 1}. {t.get('core_idea', '')}"
            for i, t in enumerate(existing_topics)
        )

    skill_template = SKILL_PATH.read_text(encoding="utf-8")
    prompt = skill_template.format(
        niche=niche,
        voice_str=voice_str,
        themes_str=themes_str,
        engagement_digest=engagement_digest,
        competitor_section=competitor_section,
        existing_topics_str=existing_topics_str,
    )

    claude_reply = message_claude(prompt)
    raw_output = getattr(claude_reply, "stdout", None)
    returncode = getattr(claude_reply, "returncode", -1)

    if claude_reply is None or returncode != 0 or not raw_output:
        logger.error(
            "Brainstorm: Claude failed for handle=%s reply=%r", handle, claude_reply
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Brainstorm failed, try again.",
        )
        return

    parsed = re.findall(r"^\s*\d+\.\s*(.+?)\s*$", raw_output, re.MULTILINE)
    topics_text = [t.strip() for t in parsed if t.strip()]

    if len(topics_text) < MIN_PARSED_TOPICS:
        logger.error(
            "Brainstorm: parsed too few topics (%d) for handle=%s raw=%r",
            len(topics_text), handle, raw_output,
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Brainstorm failed, try again.",
        )
        return

    for topic_text in topics_text:
        add_topic(user_data, topic_text)
    save_user(user_id, user_data)

    lines = [f"{i + 1}. {t}" for i, t in enumerate(topics_text)]
    message = f"✨ Brainstormed {len(topics_text)} new topics:\n\n" + "\n".join(lines)
    if len(message) > MAX_MESSAGE_LEN:
        message = message[:MAX_MESSAGE_LEN - 3] + "..."

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )

    logger.info(
        "Brainstorm complete for handle=%s added=%d generated_at=%s",
        handle, len(topics_text), datetime.now(timezone.utc).isoformat(),
    )

    from ai_social_content_generator.telegram_bot.actions.menu import brainstorm_submenu_show
    await brainstorm_submenu_show(update, context)

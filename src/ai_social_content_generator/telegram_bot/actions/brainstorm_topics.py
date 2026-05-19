import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import load_user, save_user, add_topic
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.actions.compose_carousel import build_competitor_section
from ai_social_content_generator.telegram_bot.actions.profile_skill_creator import build_engagement_digest

logger = logging.getLogger(__name__)

SKILL_PATH = Path("src/ai_social_content_generator/brainstorm_topics/SKILL.md")
POLISH_PATH = Path("src/ai_social_content_generator/brainstorm_topics/POLISH.md")
EXPAND_PATH = Path("src/ai_social_content_generator/brainstorm_topics/EXPAND.md")

MAX_MESSAGE_LEN = 4000
MIN_PARSED_TOPICS = 5
MAX_POLISHED_LEN = 200

WAITING_FOR_OWN_IDEA = 200


def _build_prompt_context(user_data: dict) -> dict | None:
    """Returns the prompt-substitution dict for brainstorm prompts.
    Returns None if analysis.json is missing or handle/niche missing."""
    if user_data is None or "handle" not in user_data or "niche" not in user_data:
        return None

    handle = user_data["handle"]
    analysis_path = Path(f"cache/{handle}-analysis.json")
    if not analysis_path.exists():
        return None

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

    return {
        "niche": niche,
        "voice_str": voice_str,
        "themes_str": themes_str,
        "engagement_digest": engagement_digest,
        "competitor_section": competitor_section,
        "existing_topics_str": existing_topics_str,
    }


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
    ctx = _build_prompt_context(user_data)
    if ctx is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please run Analyze first before brainstorming topics.",
        )
        return

    skill_template = SKILL_PATH.read_text(encoding="utf-8")
    prompt = skill_template.format(**ctx)

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


@require_auth
async def own_idea_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "Type your idea (5-15 words). Examples: "
        "'money fights between couples', 'how to apologize after a fight'"
    )
    return WAITING_FOR_OWN_IDEA


async def own_idea_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    idea = update.message.text.strip()

    if len(idea) < 3 or len(idea) > 200:
        await update.message.reply_text(
            "Idea must be between 3 and 200 characters. Try again."
        )
        return WAITING_FOR_OWN_IDEA

    context.user_data["pending_own_idea"] = idea

    keyboard = [
        [InlineKeyboardButton("✨ Polish this idea", callback_data="brainstorm_own_polish")],
        [InlineKeyboardButton("🌱 Expand to many", callback_data="brainstorm_own_expand")],
    ]
    await update.message.reply_text(
        f"Got it: '{idea}'\n\nWhat should I do with it?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END


async def brainstorm_own_process(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    idea: str,
    mode: str,
) -> None:
    query = update.callback_query
    user_id = update.effective_user.id

    if not idea:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No pending idea found. Tap 'Write my own idea' again.",
        )
        return

    progress = "Polishing your idea, ~30 sec..." if mode == "polish" else "Expanding your idea, ~30 sec..."
    await query.edit_message_text(progress)

    user_data = load_user(user_id)

    if user_data is None or "handle" not in user_data or "niche" not in user_data:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No account info. Please complete onboarding first.",
        )
        return

    handle = user_data["handle"]
    base_ctx = _build_prompt_context(user_data)
    if base_ctx is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please run Analyze first before brainstorming topics.",
        )
        return

    if mode == "polish":
        template = POLISH_PATH.read_text(encoding="utf-8")
        prompt = template.format(
            idea=idea,
            niche=base_ctx["niche"],
            voice_str=base_ctx["voice_str"],
        )
    else:
        template = EXPAND_PATH.read_text(encoding="utf-8")
        prompt = template.format(idea=idea, **base_ctx)

    claude_reply = message_claude(prompt)
    raw_output = getattr(claude_reply, "stdout", None)
    returncode = getattr(claude_reply, "returncode", -1)

    if claude_reply is None or returncode != 0 or not raw_output:
        logger.error(
            "Brainstorm-own %s: Claude failed for handle=%s reply=%r",
            mode, handle, claude_reply,
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"{mode.capitalize()} failed, try again.",
        )
        return

    if mode == "polish":
        polished = raw_output.strip().strip('"').strip("'").split("\n")[0].strip()
        if not polished or len(polished) > MAX_POLISHED_LEN:
            logger.error(
                "Brainstorm-own polish: invalid output for handle=%s raw=%r",
                handle, raw_output,
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Polish failed, try again.",
            )
            return

        add_topic(user_data, polished)
        save_user(user_id, user_data)

        message = f"✨ Polished topic added: '{polished}'"
    else:
        parsed = re.findall(r"^\s*\d+\.\s*(.+?)\s*$", raw_output, re.MULTILINE)
        topics_text = [t.strip() for t in parsed if t.strip()]

        if len(topics_text) < MIN_PARSED_TOPICS:
            logger.error(
                "Brainstorm-own expand: parsed too few topics (%d) for handle=%s raw=%r",
                len(topics_text), handle, raw_output,
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Expand failed, try again.",
            )
            return

        for topic_text in topics_text:
            add_topic(user_data, topic_text)
        save_user(user_id, user_data)

        lines = [f"{i + 1}. {t}" for i, t in enumerate(topics_text)]
        message = f"🌱 Generated {len(topics_text)} topics from your idea:\n\n" + "\n".join(lines)
        if len(message) > MAX_MESSAGE_LEN:
            message = message[:MAX_MESSAGE_LEN - 3] + "..."

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )

    context.user_data.pop("pending_own_idea", None)

    logger.info(
        "Brainstorm-own %s complete for handle=%s",
        mode, handle,
    )

    from ai_social_content_generator.telegram_bot.actions.menu import brainstorm_submenu_show
    ## await brainstorm_submenu_show(update, context)

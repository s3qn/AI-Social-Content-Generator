import json
import logging
import re
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import (
    add_headlines_to_topic,
    heal_duplicate_topic_ids,
    load_user,
    mark_headline_used,
    save_user,
)
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
    build_competitor_section,
    compose_carousel_from_picked,
)
from ai_social_content_generator.telegram_bot.actions.compose_reel import (
    compose_reel_from_picked,
)

logger = logging.getLogger(__name__)

SKILL_PATH = Path("src/ai_social_content_generator/content_picker/SKILL.md")

HEADLINES_PER_TOPIC = 8
MIN_PARSED_HOOKS = 5
MAX_REJECTED_HEADLINES = 30
TOPIC_DISPLAY_MAX = 50
HEADLINE_DISPLAY_MAX = 80


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


@require_auth
async def reel_format_picker_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    keyboard = [
        [InlineKeyboardButton(
            "📝 Text overlay (low effort, viral format)",
            callback_data="reel_format_text_overlay",
        )],
        [InlineKeyboardButton(
            "🎤 Talking head (speak to camera)",
            callback_data="reel_format_talking_head",
        )],
        [InlineKeyboardButton("← Back", callback_data="ideas_back")],
    ]

    text = (
        "How do you want this reel to look?\n\n"
        "📝 Text overlay: viewers READ text over a simple b-roll video. "
        "No speaking needed. Low effort to shoot. "
        "(Format that went viral on your account.)\n\n"
        "🎤 Talking head: you speak to the camera. More personal but "
        "more effort."
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def reel_format_picker_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "reel_format_text_overlay":
        context.user_data["pending_reel_format"] = "text_overlay"
        await content_picker_entry(update, context, "reel")
    elif query.data == "reel_format_talking_head":
        context.user_data["pending_reel_format"] = "talking_head"
        await content_picker_entry(update, context, "reel")


async def content_picker_entry(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    content_type: str,
) -> None:
    query = update.callback_query
    user_id = update.effective_user.id

    user_data = load_user(user_id)
    topics = user_data.get("topics", []) if user_data else []

    if not topics:
        keyboard = [[InlineKeyboardButton("← Back", callback_data="ideas_back")]]
        await query.edit_message_text(
            "No topics yet. Brainstorm ideas first.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    context.user_data["picker_content_type"] = content_type
    await topic_picker_show(update, context, content_type)


async def topic_picker_show(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    content_type: str,
) -> None:
    query = update.callback_query
    user_id = update.effective_user.id

    user_data = load_user(user_id)
    topics = user_data.get("topics", []) if user_data else []

    if not topics:
        keyboard = [[InlineKeyboardButton("← Back", callback_data="ideas_back")]]
        await query.edit_message_text(
            "No topics yet. Brainstorm ideas first.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    lines: list[str] = []
    for i, topic in enumerate(topics, start=1):
        core = topic.get("core_idea", "")
        lines.append(f"{i}. {_truncate(core, TOPIC_DISPLAY_MAX)}")
    text = f"📌 Pick a topic for your {content_type}:\n\n" + "\n".join(lines)

    buttons = [
        InlineKeyboardButton(
            str(i + 1), callback_data=f"topic_pick_{content_type}_{i}"
        )
        for i in range(len(topics))
    ]
    keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    keyboard.append([InlineKeyboardButton("← Back", callback_data="ideas_back")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def topic_picker_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    payload = query.data.removeprefix("topic_pick_")
    parts = payload.split("_", 1)
    if len(parts) != 2:
        logger.error("topic_picker_route: bad callback_data=%r", query.data)
        return
    content_type, index_str = parts
    try:
        topic_index = int(index_str)
    except ValueError:
        logger.error("topic_picker_route: bad index in callback_data=%r", query.data)
        return

    user_data = load_user(user_id)
    topics = user_data.get("topics", []) if user_data else []

    if topic_index < 0 or topic_index >= len(topics):
        keyboard = [[InlineKeyboardButton("← Back", callback_data="brainstorm_back")]]
        await query.edit_message_text(
            "Topic not found, please try again.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    core_idea = topics[topic_index].get("core_idea", "")

    # Stash NOW: the headline_mode_* handlers fire later with no payload,
    # so they read the topic/type from user_data.
    context.user_data["pending_topic_index"] = topic_index
    context.user_data["pending_content_type"] = content_type
    # pending_reel_format was already set earlier in the reel path; untouched.
    # A newly picked topic starts with a clean regen accumulator, even when
    # the user got here through the menu instead of "Back to topic picker".
    context.user_data.pop("rejected_headlines", None)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Generate with AI", callback_data="headline_mode_ai")],
        [InlineKeyboardButton("✍️ Write your own", callback_data="headline_mode_own")],
        [InlineKeyboardButton("← Back to topic picker", callback_data="topic_picker_back")],
    ])
    await query.edit_message_text(
        f"Topic: {core_idea}\n\nGenerate headline options with AI, or write your own?",
        reply_markup=keyboard,
    )


@require_auth
async def headline_mode_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    topic_index = context.user_data.get("pending_topic_index")
    content_type = context.user_data.get("pending_content_type")
    if not isinstance(topic_index, int) or content_type not in ("carousel", "reel"):
        await query.edit_message_text("Pick a topic again.")
        return

    if query.data == "headline_mode_ai":
        await headline_picker_generate(update, context, content_type, topic_index)
    else:
        context.user_data["awaiting_custom_headline"] = True
        await query.edit_message_text(
            f"✍️ Type your headline (the hook for this {content_type}). "
            "It will be used as-is."
        )


@require_auth
async def headline_regen_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    topic_index = context.user_data.get("pending_topic_index")
    content_type = context.user_data.get("pending_content_type")
    if not isinstance(topic_index, int) or content_type not in ("carousel", "reel"):
        await query.edit_message_text("Pick a topic again.")
        return

    rejected = context.user_data.setdefault("rejected_headlines", [])
    rejected.extend(context.user_data.get("pending_headlines", []))
    del rejected[:-MAX_REJECTED_HEADLINES]

    await headline_picker_generate(update, context, content_type, topic_index)


async def headline_picker_generate(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    content_type: str,
    topic_index: int,
) -> None:
    query = update.callback_query
    user_id = update.effective_user.id

    user_data = load_user(user_id)
    if user_data is None or "handle" not in user_data or "niche" not in user_data:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No account info. Please complete onboarding first.",
        )
        return

    topics = user_data.get("topics", [])
    if topic_index < 0 or topic_index >= len(topics):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Topic not found, please try again.",
        )
        return

    topic = topics[topic_index]
    core_idea = topic.get("core_idea", "")
    topic_id = topic.get("id", "")

    handle = user_data["handle"]
    analysis_path = Path(f"cache/{handle}-analysis.json")
    if not analysis_path.exists():
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please run Analyze first before generating headlines.",
        )
        return

    await query.edit_message_text(
        f"Generating {HEADLINES_PER_TOPIC} headlines, ~30 sec..."
    )

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    voice = analysis.get("voice", [])
    voice_str = ", ".join(voice) if isinstance(voice, list) else str(voice)
    niche = analysis.get("niche") or user_data.get("niche", "")

    competitors = user_data.get("competitors", [])
    competitor_section = build_competitor_section(competitors)

    rejected = context.user_data.get("rejected_headlines", [])
    if rejected:
        listing = "\n".join(f"- {h}" for h in rejected)
        previous_headlines_section = (
            "ALREADY GENERATED (the user rejected ALL of these — do NOT repeat "
            "them or produce close variants/paraphrases):\n"
            f"{listing}\n\n"
            "Take genuinely DIFFERENT angles: different emotional registers, "
            "different structures (question vs statement vs story-opener vs "
            "stat), different aspects of the topic.\n"
        )
    else:
        previous_headlines_section = ""

    skill_template = SKILL_PATH.read_text(encoding="utf-8")
    prompt = skill_template.format(
        content_type=content_type,
        topic=core_idea,
        niche=niche,
        voice_str=voice_str,
        competitor_section=competitor_section,
        previous_headlines_section=previous_headlines_section,
    )

    claude_reply = await message_claude(prompt)
    raw_output = getattr(claude_reply, "stdout", "") or ""
    returncode = getattr(claude_reply, "returncode", -1)

    if claude_reply is None or returncode != 0 or not raw_output:
        logger.error(
            "Content picker: Claude failed for topic_id=%s content_type=%s reply=%r",
            topic_id, content_type, claude_reply,
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Headline generation failed, try again.",
        )
        return

    parsed = re.findall(r"^\s*\d+\.\s*(.+?)\s*$", raw_output, re.MULTILINE)
    headlines = [h.strip() for h in parsed if h.strip()]

    if len(headlines) < MIN_PARSED_HOOKS:
        logger.error(
            "Content picker: parsed too few hooks (%d) for topic_id=%s raw=%r",
            len(headlines), topic_id, raw_output,
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Headline generation failed, try again.",
        )
        return

    context.user_data["pending_headlines"] = headlines
    context.user_data["pending_topic_id"] = topic_id
    context.user_data["pending_topic_index"] = topic_index
    context.user_data["pending_content_type"] = content_type

    await headline_picker_show(update, context)


async def headline_picker_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query

    headlines: list[str] = context.user_data.get("pending_headlines", [])
    content_type: str = context.user_data.get("pending_content_type", "carousel")

    if not headlines:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No pending headlines. Please pick a topic again.",
        )
        return

    lines = [
        f"{i + 1}. {_truncate(h, HEADLINE_DISPLAY_MAX)}"
        for i, h in enumerate(headlines)
    ]
    text = f"💡 Pick a hook for your {content_type}:\n\n" + "\n".join(lines)

    buttons = [
        InlineKeyboardButton(
            str(i + 1), callback_data=f"headline_pick_{content_type}_{i}"
        )
        for i in range(len(headlines))
    ]
    keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    keyboard.append(
        [InlineKeyboardButton("🔄 Regenerate headlines", callback_data="headline_regen")]
    )
    keyboard.append(
        [InlineKeyboardButton("✍️ Write your own", callback_data="headline_mode_own")]
    )
    keyboard.append(
        [InlineKeyboardButton("← Back to topic picker", callback_data="topic_picker_back")]
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def headline_picker_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    payload = query.data.removeprefix("headline_pick_")
    parts = payload.split("_", 1)
    if len(parts) != 2:
        logger.error("headline_picker_route: bad callback_data=%r", query.data)
        return
    content_type, index_str = parts
    try:
        index = int(index_str)
    except ValueError:
        logger.error("headline_picker_route: bad index in callback_data=%r", query.data)
        return

    headlines: list[str] = context.user_data.get("pending_headlines", [])
    if index < 0 or index >= len(headlines):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Headline not found, please pick again.",
        )
        return

    chosen_headline = headlines[index]

    if content_type not in ("carousel", "reel"):
        logger.error("headline_picker_route: unknown content_type=%r", content_type)
        return

    await _use_headline(update, context, chosen_headline)


def _clear_picker_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "pending_headlines",
        "pending_topic_id",
        "pending_topic_index",
        "pending_content_type",
        "pending_reel_format",
        "rejected_headlines",
        "awaiting_custom_headline",
    ):
        context.user_data.pop(key, None)


async def _use_headline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    headline: str,
) -> None:
    """Shared tail for a picked OR custom headline: vault bookkeeping,
    then compose. Reached from a callback (numbered pick) or a plain text
    message (custom headline), so progress text can't assume a query."""
    query = update.callback_query
    user_id = update.effective_user.id

    async def _say(text: str) -> None:
        if query is not None:
            await query.edit_message_text(text)
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text=text
            )

    content_type = context.user_data.get("pending_content_type")
    topic_index = context.user_data.get("pending_topic_index")

    user_data = load_user(user_id)
    topics = user_data.get("topics", []) if user_data else []

    if (
        content_type not in ("carousel", "reel")
        or not isinstance(topic_index, int)
        or topic_index < 0
        or topic_index >= len(topics)
    ):
        _clear_picker_state(context)
        await _say("Topic no longer exists. Pick a topic again.")
        return

    heal_duplicate_topic_ids(user_data)

    topic = topics[topic_index]
    topic_id = topic["id"]
    topic_core_idea = topic.get("core_idea", "")

    add_headlines_to_topic(user_data, topic_id, [headline])
    mark_headline_used(user_data, topic_id, headline)
    save_user(user_id, user_data)

    if content_type == "carousel":
        await _say(
            f"📜 Generating carousel using:\n\n"
            f"Topic: {topic_core_idea}\n"
            f"Hook: {headline}\n\n"
            f"~30-60 sec..."
        )
        await compose_carousel_from_picked(
            update, context, topic_core_idea, headline
        )
    else:
        reel_format = context.user_data.get(
            "pending_reel_format", "talking_head"
        )
        await _say(
            f"🎥 Generating reel using:\n\n"
            f"Topic: {topic_core_idea}\n"
            f"Hook: {headline}\n\n"
            f"~30-60 sec..."
        )
        await compose_reel_from_picked(
            update, context, topic_core_idea, headline,
            reel_format=reel_format,
        )

    _clear_picker_state(context)


@require_auth
async def topic_picker_back_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    # New topic = fresh start: rejected headlines from the abandoned topic
    # must not constrain the next one, and a pending custom-headline prompt
    # is moot once the user backs out.
    context.user_data.pop("rejected_headlines", None)
    context.user_data.pop("awaiting_custom_headline", None)

    content_type = context.user_data.get("pending_content_type", "carousel")
    await topic_picker_show(update, context, content_type)

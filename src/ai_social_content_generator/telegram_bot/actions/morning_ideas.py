import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import load_user
from ai_social_content_generator.telegram_bot.actions.content_picker import (
    headline_picker_generate,
)

logger = logging.getLogger(__name__)

IDEAS_PER_BRIEF = 3
BUTTON_LABEL_MAX = 60


def _truncate(text: str, max_len: int = BUTTON_LABEL_MAX) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def build_topics_message(chosen: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    """Build the morning brief message + keyboard from a non-empty list
    of topic dicts. One button per topic, label = core_idea truncated,
    callback_data = idea_pick_{topic_id}. Caller handles the empty case."""
    buttons: list[list[InlineKeyboardButton]] = []
    for topic in chosen:
        label = _truncate(topic.get("core_idea", "(no idea)"))
        buttons.append([
            InlineKeyboardButton(
                label, callback_data=f"idea_pick_{topic['id']}"
            )
        ])

    text = (
        "✨ Morning Ideas\n\n"
        "Three topics from your vault. Tap one to compose."
    )
    return text, InlineKeyboardMarkup(buttons)


@require_auth
async def morning_idea_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle a tap on a morning-idea button (^idea_pick_{topic_id}).
    Resolves topic_id → current index, then asks Carousel/Reel."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    topic_id = query.data.removeprefix("idea_pick_")

    user_data = load_user(user_id)
    if user_data is None:
        await query.edit_message_text(
            "No account info. Please complete onboarding first."
        )
        return

    topics = user_data.get("topics", [])
    idx = next(
        (i for i, t in enumerate(topics) if t.get("id") == topic_id),
        None,
    )
    if idx is None:
        logger.info(
            "Morning idea stale: user_id=%s topic_id=%s no longer in vault",
            user_id, topic_id,
        )
        await query.edit_message_text(
            "That idea is no longer available. Open the menu to see what's queued."
        )
        return

    topic = topics[idx]
    core_idea = topic.get("core_idea", "")

    keyboard = [
        [
            InlineKeyboardButton(
                "📜 Carousel", callback_data=f"briefpick_carousel_{idx}"
            ),
            InlineKeyboardButton(
                "🎥 Reel", callback_data=f"briefpick_reel_{idx}"
            ),
        ],
    ]
    text = f"Topic: {core_idea}\n\nCarousel or Reel?"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


def _parse_index(payload: str) -> int | None:
    """Extracts integer index from 'content_type_index' or 'format_index'."""
    parts = payload.rsplit("_", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


@require_auth
async def morning_idea_format_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handles ^briefpick_ (Carousel/Reel) and ^briefreel_ (talking/text-overlay).

    Bridges into headline_picker_generate with the FRESHLY-VALIDATED index,
    bypassing topic_picker (topic was already chosen at idea-tap time)."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    data = query.data

    if data.startswith("briefpick_"):
        payload = data.removeprefix("briefpick_")
        topic_index = _parse_index(payload)
        if topic_index is None:
            logger.error("morning_idea_format_route: bad briefpick payload=%r", data)
            return
        content_type = payload.rsplit("_", 1)[0]
        if content_type not in ("carousel", "reel"):
            logger.error("morning_idea_format_route: bad content_type=%r", content_type)
            return

        if not _index_valid(user_id, topic_index):
            await query.edit_message_text(
                "That idea is no longer available. Open the menu to see what's queued."
            )
            return

        if content_type == "carousel":
            await headline_picker_generate(
                update, context, "carousel", topic_index
            )
            return

        # Reel: ask format sub-choice (talking head vs text overlay).
        keyboard = [
            [InlineKeyboardButton(
                "🎤 Talking head",
                callback_data=f"briefreel_talking_{topic_index}",
            )],
            [InlineKeyboardButton(
                "📝 Text overlay",
                callback_data=f"briefreel_text_{topic_index}",
            )],
        ]
        await query.edit_message_text(
            "Reel format?", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("briefreel_"):
        payload = data.removeprefix("briefreel_")
        topic_index = _parse_index(payload)
        if topic_index is None:
            logger.error("morning_idea_format_route: bad briefreel payload=%r", data)
            return
        fmt_token = payload.rsplit("_", 1)[0]
        fmt_map = {"talking": "talking_head", "text": "text_overlay"}
        reel_format = fmt_map.get(fmt_token)
        if reel_format is None:
            logger.error("morning_idea_format_route: bad reel format=%r", fmt_token)
            return

        if not _index_valid(user_id, topic_index):
            await query.edit_message_text(
                "That idea is no longer available. Open the menu to see what's queued."
            )
            return

        context.user_data["pending_reel_format"] = reel_format
        await headline_picker_generate(
            update, context, "reel", topic_index
        )
        return

    logger.error("morning_idea_format_route: unknown callback_data=%r", data)


def _index_valid(user_id: int, topic_index: int) -> bool:
    """Re-validate that topic_index is still in range — the topic list may
    have shifted between idea-tap and format-tap."""
    user_data = load_user(user_id)
    if user_data is None:
        return False
    topics = user_data.get("topics", [])
    return 0 <= topic_index < len(topics)

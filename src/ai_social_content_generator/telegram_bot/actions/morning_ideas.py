import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import (
    load_user,
    mark_headline_used,
    save_user,
)
from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
    compose_carousel_from_picked,
)

logger = logging.getLogger(__name__)

IDEAS_PER_BRIEF = 3
BUTTON_LABEL_MAX = 60


def build_ideas_message(unused: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    """Build the morning brief message + keyboard from non-empty unused
    list. Dedupes by topic_id (one button per topic, first unused only),
    caps to IDEAS_PER_BRIEF buttons. Caller handles the empty case."""
    seen: set[str] = set()
    picks: list[dict] = []
    for item in unused:
        tid = item.get("topic_id")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        picks.append(item)
        if len(picks) >= IDEAS_PER_BRIEF:
            break

    buttons: list[list[InlineKeyboardButton]] = []
    for item in picks:
        label = item.get("headline_text", "(no headline)")
        if len(label) > BUTTON_LABEL_MAX:
            label = label[: BUTTON_LABEL_MAX - 3] + "..."
        buttons.append([
            InlineKeyboardButton(
                label, callback_data=f"idea_pick_{item['topic_id']}"
            )
        ])

    text = (
        "✨ Morning Ideas\n\n"
        "Here are unused headlines from your vault. Tap one to compose a carousel."
    )
    return text, InlineKeyboardMarkup(buttons)


@require_auth
async def morning_idea_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle a tap on a morning-idea button. Resolves the topic + its
    first unused headline, marks the headline used, persists, then
    routes into the carousel compose flow."""
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

    topic = next(
        (t for t in user_data.get("topics", []) if t.get("id") == topic_id),
        None,
    )
    if topic is None:
        await query.edit_message_text(
            "That idea is no longer available. Open the menu to see what's queued."
        )
        return

    headline_obj = next(
        (h for h in topic.get("headlines", []) if not h.get("used")),
        None,
    )
    if headline_obj is None:
        await query.edit_message_text(
            "That idea is no longer available. Open the menu to see what's queued."
        )
        return

    chosen_headline = headline_obj["text"]
    topic_core_idea = topic.get("core_idea", "")

    mark_headline_used(user_data, topic_id, chosen_headline)
    save_user(user_id, user_data)

    await query.edit_message_text(
        f"📜 Generating carousel using:\n\n"
        f"Topic: {topic_core_idea}\n"
        f"Hook: {chosen_headline}\n\n"
        f"~30-60 sec..."
    )

    logger.info(
        "Morning idea tap: user_id=%s topic_id=%s — entering compose",
        user_id, topic_id,
    )
    await compose_carousel_from_picked(
        update, context, topic_core_idea, chosen_headline
    )

"""Shared UI helpers: a keep-alive typing indicator and a universal
cancel for text-input flows. No project imports beyond auth, so any action
module can import this without cycle risk.

ADDING A NEW INPUT FLOW? Two steps keep cancel working:
  1. add its user_data key to INPUT_FLOW_KEYS below, and
  2. attach CANCEL_BUTTON to the prompt that sets the flag.
A missed key = a cancel that doesn't unstick that flow.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Feature 1 — keep-alive "typing…" indicator.
# ----------------------------------------------------------------------

@asynccontextmanager
async def typing_action(bot, chat_id: int, interval: float = 4.0):
    """Show 'typing…' continuously for the duration of the with-block.

    Telegram's chat action auto-expires after ~5s, so we re-send every
    `interval` seconds. Per-call scoped (the task is local, chat_id is an
    argument) → multi-user safe. The finally ALWAYS stops the loop, even if
    the wrapped op raises, so a failed operation can't leave typing stuck."""
    async def _loop():
        try:
            while True:
                try:
                    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                except Exception:
                    # A transient send failure must not kill the loop or the op.
                    pass
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ----------------------------------------------------------------------
# Feature 2 — universal cancel for text/media input flows.
# ----------------------------------------------------------------------

# EVERY user_data key that gates capture of the next message (or is working
# state for such a flow). Cancel clears all of them: "get me out of whatever
# input I'm in." Keep this COMPLETE — see the module docstring.
INPUT_FLOW_KEYS = [
    # text/media capture gates
    "awaiting_viral_keyword",
    "editing_slide",
    "awaiting_custom_headline",
    "awaiting_format_name",
    "awaiting_format_desc",
    "pending_viral_import",
    "awaiting_schedule_time",
    "awaiting_carousel_instructions",
    "awaiting_bg_upload",
    "awaiting_logo_upload",
    # companion / working state cleared alongside the gates
    "pending_format",
    "pending_schedule",
    "pending_own_idea",
    "pending_topic_id",
    "pending_topic_index",
    "pending_content_type",
    "pending_reel_format",
    "pending_headlines",
]

CANCEL_BUTTON = InlineKeyboardButton("✖ Cancel", callback_data="cancel_input")


def cancel_markup() -> InlineKeyboardMarkup:
    """A standalone keyboard with just the cancel button."""
    return InlineKeyboardMarkup([[CANCEL_BUTTON]])


def clear_input_flows(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pop every input-flow key (idempotent — popping absent keys is fine)."""
    for k in INPUT_FLOW_KEYS:
        context.user_data.pop(k, None)


@require_auth
async def cancel_input_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Clear all pending input flows and acknowledge. Reachable from the
    ✖ Cancel button on any text-input prompt."""
    query = update.callback_query
    await query.answer()
    clear_input_flows(context)
    try:
        await query.edit_message_text("✖ Cancelled.")
    except Exception:
        # The prompt may be a photo/caption message that can't be edited to
        # text; fall back to a fresh message.
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="✖ Cancelled.",
        )

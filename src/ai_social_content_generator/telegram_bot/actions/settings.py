import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import (
    get_reminder_schedule,
    load_user,
    save_user,
    set_reminder_schedule,
)
from ai_social_content_generator.telegram_bot.scheduler import (
    cancel_reminder_for_user,
    schedule_reminder_for_user,
)

logger = logging.getLogger(__name__)


@require_auth
async def settings_submenu_show(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Top-level Settings submenu: shows Edit niche + Scheduler buttons."""
    user_id = update.effective_user.id
    user_data = load_user(user_id)
    schedule = get_reminder_schedule(user_data) if user_data else {"enabled": False, "slot": None}

    if schedule["enabled"]:
        scheduler_label = f"⏰ Scheduler ({schedule['slot']})"
    else:
        scheduler_label = "⏰ Scheduler (off)"

    keyboard = [
        [InlineKeyboardButton("✏️ Edit niche", callback_data="settings_edit_niche")],
        [InlineKeyboardButton(scheduler_label, callback_data="settings_scheduler")],
        [InlineKeyboardButton("← Back", callback_data="settings_back")],
    ]

    text = "⚙️ Settings"

    query = update.callback_query
    if query is not None:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


@require_auth
async def settings_submenu_route(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Dispatch from settings submenu buttons."""
    query = update.callback_query
    await query.answer()

    if query.data == "settings_edit_niche":
        await query.edit_message_text(
            "Edit niche is coming soon. Returning to settings...",
        )
        await settings_submenu_show(update, context)
    elif query.data == "settings_scheduler":
        await scheduler_submenu_show(update, context)
    elif query.data == "settings_back":
        from ai_social_content_generator.telegram_bot.actions.menu import (
            _main_menu_keyboard,
        )
        await query.edit_message_text(
            "What would you like to do?",
            reply_markup=_main_menu_keyboard(),
        )


@require_auth
async def scheduler_submenu_show(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Scheduler submenu: shows Morning / Evening / Off + current status."""
    user_id = update.effective_user.id
    user_data = load_user(user_id)
    schedule = get_reminder_schedule(user_data) if user_data else {"enabled": False, "slot": None}

    if schedule["enabled"]:
        status = f"Currently: {schedule['slot']} (Jerusalem time)"
    else:
        status = "Currently: off"

    text = (
        "⏰ Daily Post Reminder\n\n"
        f"{status}\n\n"
        "Choose when to be reminded:\n"
        "- Morning: 09:00 Jerusalem\n"
        "- Evening: 18:00 Jerusalem\n"
        "- Off: no reminders"
    )

    keyboard = [
        [InlineKeyboardButton("🌅 Morning (09:00)", callback_data="scheduler_set_morning")],
        [InlineKeyboardButton("🌆 Evening (18:00)", callback_data="scheduler_set_evening")],
        [InlineKeyboardButton("🔕 Off", callback_data="scheduler_set_off")],
        [InlineKeyboardButton("← Back", callback_data="scheduler_back")],
    ]

    query = update.callback_query
    if query is not None:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


@require_auth
async def scheduler_submenu_route(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle scheduler choice."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data == "scheduler_back":
        await settings_submenu_show(update, context)
        return

    user_data = load_user(user_id)
    if user_data is None:
        await query.edit_message_text("No account info. Please /start first.")
        return

    if query.data == "scheduler_set_morning":
        set_reminder_schedule(user_data, enabled=True, slot="morning")
        save_user(user_id, user_data)
        schedule_reminder_for_user(context.application, user_id, "morning")
        await query.answer("Morning reminder set ✓", show_alert=False)
    elif query.data == "scheduler_set_evening":
        set_reminder_schedule(user_data, enabled=True, slot="evening")
        save_user(user_id, user_data)
        schedule_reminder_for_user(context.application, user_id, "evening")
        await query.answer("Evening reminder set ✓", show_alert=False)
    elif query.data == "scheduler_set_off":
        set_reminder_schedule(user_data, enabled=False, slot=None)
        save_user(user_id, user_data)
        cancel_reminder_for_user(context.application, user_id)
        await query.answer("Reminders off ✓", show_alert=False)

    await scheduler_submenu_show(update, context)

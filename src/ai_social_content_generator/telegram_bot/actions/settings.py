import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ai_social_content_generator.instagram.oauth import build_authorize_url
from ai_social_content_generator.instagram.oauth_state import issue_state
from ai_social_content_generator.instagram.token_store import get_token
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

    ig_label = (
        "📷 Instagram (connected)" if get_token(user_id) else "📷 Connect Instagram"
    )

    keyboard = [
        [InlineKeyboardButton("✏️ Edit niche", callback_data="settings_edit_niche")],
        [InlineKeyboardButton(scheduler_label, callback_data="settings_scheduler")],
        [InlineKeyboardButton("🎨 Customize carousel", callback_data="settings_customize")],
        [InlineKeyboardButton(ig_label, callback_data="settings_connect_ig")],
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
    elif query.data == "settings_customize":
        await customize_submenu_show(update, context)
    elif query.data == "settings_connect_ig":
        await instagram_connect_show(update, context)
    elif query.data == "settings_back":
        from ai_social_content_generator.telegram_bot.actions.menu import (
            _main_menu_keyboard,
        )
        await query.edit_message_text(
            "What would you like to do?",
            reply_markup=_main_menu_keyboard(),
        )


@require_auth
async def customize_submenu_show(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Sub-menu under Settings: Background + Logo + Re-render + Back."""
    keyboard = [
        [InlineKeyboardButton("🖼 Background", callback_data="customize_background")],
        [InlineKeyboardButton("🏷 Logo", callback_data="customize_logo")],
        [InlineKeyboardButton("🔄 Re-render current carousel", callback_data="customize_rerender")],
        [InlineKeyboardButton("← Back", callback_data="customize_back")],
    ]
    text = "🎨 Customize carousel"
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
async def customize_submenu_route(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Dispatch from the Customize-carousel sub-menu."""
    query = update.callback_query
    await query.answer()

    if query.data == "customize_background":
        context.user_data["awaiting_bg_upload"] = True
        await query.edit_message_text(
            "🖼 Send me an image to use as your carousel background.\n\n"
            "Rules for a clean result:\n"
            "1. No text on the image — no title, subtitle, or handle. The bot adds all text.\n"
            "2. Portrait 4:5 (1080×1350) works best.\n"
            "3. Leave a calm area (top or middle) for the text to sit.\n\n"
            "Send the photo now, or tap /cancel."
        )
    elif query.data == "customize_logo":
        context.user_data["awaiting_logo_upload"] = True
        await query.edit_message_text(
            "🏷 Send your logo as a FILE (paperclip → File), NOT as a photo — "
            "sending as a photo flattens transparency.\n\n"
            "Use a transparent PNG, roughly square. It will appear on the hook "
            "and final slides in place of the default motif.\n\n"
            "Send the file now, or tap /cancel."
        )
    elif query.data == "customize_rerender":
        # Render logic lives in compose_carousel; settings just routes here.
        # Local import avoids an import cycle (compose_carousel pulls nothing
        # from settings, but keep the boundary tidy).
        from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
            rerender_current_carousel,
        )
        await rerender_current_carousel(update, context)
    elif query.data == "customize_back":
        await settings_submenu_show(update, context)


@require_auth
async def instagram_connect_show(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Show the Connect-Instagram screen. If already connected, surface
    that and offer to reconnect. Otherwise mint a fresh single-use state,
    build the authorize URL, and present it as a tappable URL button."""
    user_id = update.effective_user.id
    already = get_token(user_id)

    try:
        state = issue_state(user_id)
        authorize_url = build_authorize_url(state)
    except Exception:
        logger.exception("Failed to build Instagram authorize URL for user_id=%s", user_id)
        query = update.callback_query
        if query is not None:
            await query.edit_message_text(
                "Instagram isn't configured on this bot yet. Check back later.",
            )
        return

    if already:
        text = (
            "📷 Instagram is connected.\n\n"
            f"Account id: {already.get('ig_account_id', 'unknown')}\n\n"
            "Tap below to reconnect (e.g. after changing accounts)."
        )
        button_label = "🔄 Reconnect Instagram"
    else:
        text = (
            "📷 Connect your Instagram Business account.\n\n"
            "Tap below, approve the app on Instagram, and you'll be sent back "
            "to a confirmation page. Return here when done."
        )
        button_label = "Open Instagram authorize page"

    keyboard = [
        [InlineKeyboardButton(button_label, url=authorize_url)],
        [InlineKeyboardButton("← Back", callback_data="settings_back")],
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


@require_auth
async def receive_background_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Global filters.PHOTO handler. Flag-gated: returns immediately
    unless context.user_data['awaiting_bg_upload'] is True. The gate is
    the FIRST line so stray photos (no other flow expects user photos
    today) are silently ignored."""
    if not context.user_data.get("awaiting_bg_upload"):
        return
    # Consume the flag immediately so a subsequent stray photo isn't
    # treated as a new upload.
    context.user_data["awaiting_bg_upload"] = False

    user_id = update.effective_user.id
    user_data = load_user(user_id)
    if not user_data or "handle" not in user_data:
        await update.message.reply_text(
            "Please complete onboarding first."
        )
        return
    handle = user_data["handle"]

    if not update.message or not update.message.photo:
        await update.message.reply_text(
            "That wasn't a photo. Open Settings → Carousel background and try again."
        )
        return

    photo = update.message.photo[-1]  # largest size
    tg_file = await photo.get_file()
    dest = Path("cache") / f"{handle}-bg.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    await tg_file.download_to_drive(custom_path=str(dest))

    user_data["carousel_background"] = str(dest)
    save_user(user_id, user_data)
    logger.info(
        "Saved carousel background for user_id=%s handle=%s -> %s",
        user_id, handle, dest,
    )

    await update.message.reply_text(
        "✅ Background saved. Your next carousel images will use it."
    )

    # Render one preview slide so the user can spot a baked-in-text
    # collision before relying on it. Non-fatal — the bg is already saved.
    try:
        from ai_social_content_generator.render.carousel_render import (
            render_carousel,
        )
        from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
            _resolve_logo,
        )
        sample = [
            {
                "type": "hook",
                "n": 1,
                "text": "דוגמה: *הכותרת שלך* כאן",
                "sub": None,
            }
        ]
        out_dir = Path("cache") / "render" / str(user_id) / "bg_preview"
        paths = await render_carousel(
            sample, handle, dest, out_dir, logo_path=_resolve_logo(user_id),
        )
        if paths:
            with open(paths[0], "rb") as f:
                await update.message.reply_photo(
                    photo=f,
                    caption="Preview — is the text clear and uncluttered?",
                )
    except Exception:
        logger.exception(
            "Background preview render failed for user_id=%s", user_id,
        )


@require_auth
async def receive_logo_document(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Global filters.Document.IMAGE handler. Flag-gated on
    awaiting_logo_upload (gate is the FIRST line so stray document
    uploads in unrelated chats are silently ignored). The flag is
    consumed immediately to avoid double-fires.

    The doc bytes are saved raw — Telegram only preserves transparency
    for documents, not photos. That's why the prompt insists the user
    sends as a FILE rather than a photo."""
    if not context.user_data.get("awaiting_logo_upload"):
        return
    context.user_data["awaiting_logo_upload"] = False

    user_id = update.effective_user.id
    user_data = load_user(user_id)
    if not user_data or "handle" not in user_data:
        await update.message.reply_text("Please complete onboarding first.")
        return
    handle = user_data["handle"]

    doc = update.message.document if update.message else None
    if not doc or not (doc.mime_type or "").startswith("image/"):
        await update.message.reply_text(
            "That wasn't an image file. Open Settings → Customize carousel → "
            "Logo and send a transparent PNG as a FILE."
        )
        return

    tg_file = await doc.get_file()
    dest = Path("cache") / f"{handle}-logo.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    await tg_file.download_to_drive(custom_path=str(dest))

    user_data["carousel_logo"] = str(dest)
    save_user(user_id, user_data)
    logger.info(
        "Saved carousel logo for user_id=%s handle=%s -> %s", user_id, handle, dest,
    )

    await update.message.reply_text(
        "✅ Logo saved. It will appear on your hook and final slides."
    )

    # Hook-slide preview WITH the logo so the user can spot a white box
    # or background fringe before relying on it. Needs a background to
    # render against — fall back to the user's current bg or the default.
    try:
        from ai_social_content_generator.render.carousel_render import (
            render_carousel,
        )
        from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
            _resolve_background,
        )
        sample = [
            {
                "type": "hook",
                "n": 1,
                "text": "דוגמה: *הכותרת שלך* כאן",
                "sub": None,
            }
        ]
        out_dir = Path("cache") / "render" / str(user_id) / "logo_preview"
        paths = await render_carousel(
            sample, handle, _resolve_background(user_id), out_dir, logo_path=dest,
        )
        if paths:
            with open(paths[0], "rb") as f:
                await update.message.reply_photo(
                    photo=f,
                    caption=(
                        "Preview — is the logo clean (no white box)? "
                        "If it has a background, re-send a transparent PNG."
                    ),
                )
    except Exception:
        logger.exception("Logo preview render failed for user_id=%s", user_id)

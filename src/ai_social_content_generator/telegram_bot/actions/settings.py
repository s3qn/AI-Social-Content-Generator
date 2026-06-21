import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ai_social_content_generator.instagram.oauth import build_authorize_url
from ai_social_content_generator.instagram.oauth_state import issue_state
from ai_social_content_generator.instagram.token_store import get_token
from ai_social_content_generator.facebook.oauth import (
    build_authorize_url as fb_build_authorize_url,
)
from ai_social_content_generator.facebook.token_store import get_fb_token
from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import (
    get_autopost,
    get_reminder_schedule,
    load_user,
    save_user,
    set_autopost,
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
        [InlineKeyboardButton("🎨 Carousel settings", callback_data="settings_customize")],
        [InlineKeyboardButton("📤 Autopost settings", callback_data="autopost_settings")],
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
    """Sub-menu under Settings: Background + Logo + My instructions +
    Re-render + Back. The single carousel-settings home (consolidates the
    former Customize submenu; My instructions is added here)."""
    keyboard = [
        [InlineKeyboardButton("🖼 Background", callback_data="customize_background")],
        [InlineKeyboardButton("🏷 Logo", callback_data="customize_logo")],
        [InlineKeyboardButton("✍️ My instructions", callback_data="carousel_instructions")],
        [InlineKeyboardButton("🔄 Re-render current carousel", callback_data="customize_rerender")],
        [InlineKeyboardButton("← Back", callback_data="customize_back")],
    ]
    text = "🎨 Carousel settings"
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
    # Keyed by user_id, NOT handle: two users can manage the same IG account
    # (preference files are per-person; scrape caches stay per-handle deliberately).
    dest = Path("cache") / f"{user_id}-bg.jpg"
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
    # Keyed by user_id, NOT handle: two users can manage the same IG account
    # (preference files are per-person; scrape caches stay per-handle deliberately).
    dest = Path("cache") / f"{user_id}-logo.png"
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


# ----------------------------------------------------------------------
# Custom carousel instructions (additive, subordinate to the SKILL rules).
# ----------------------------------------------------------------------

CAROUSEL_INSTRUCTIONS_MAX = 1500


def _get_carousel_instructions(user_data: dict | None) -> str:
    if not user_data:
        return ""
    return (user_data.get("custom_instructions") or {}).get("carousel", "").strip()


@require_auth
async def carousel_instructions_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show the creator's current carousel instructions + Set/Clear."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    current = _get_carousel_instructions(load_user(user_id))
    body = f"Your current instructions:\n\n{current}" if current else "None set yet."

    text = (
        "✍️ My carousel instructions\n\n"
        f"{body}\n\n"
        "Your instructions guide tone and style. The post format and rules "
        "stay intact."
    )
    keyboard = [
        [InlineKeyboardButton("✏️ Set / edit", callback_data="carousel_instr_edit")],
        [InlineKeyboardButton("🗑 Clear", callback_data="carousel_instr_clear")],
        [InlineKeyboardButton("← Back", callback_data="settings_customize")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


@require_auth
async def carousel_instr_edit(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Arm the text capture for the next message."""
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_carousel_instructions"] = True
    await query.edit_message_text(
        "✍️ Send your instructions for carousels (tone, style, what to avoid).\n\n"
        "They're added on top of the existing system, which keeps the post "
        f"format and rules intact. Keep it under {CAROUSEL_INSTRUCTIONS_MAX} "
        "characters."
    )


@require_auth
async def carousel_instr_clear(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Clear the stored instructions; carousels return to default."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    user_data = load_user(user_id)
    if user_data is not None:
        ci = user_data.get("custom_instructions")
        if isinstance(ci, dict):
            ci.pop("carousel", None)
        save_user(user_id, user_data)

    keyboard = [[InlineKeyboardButton("← Back", callback_data="carousel_instructions")]]
    await query.edit_message_text(
        "Cleared. Your carousels are back to the default style.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def receive_carousel_instructions(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """message_bot branch for awaiting_carousel_instructions. Validates
    length, stores under custom_instructions.carousel, clears the flag."""
    text = (update.message.text or "").strip()
    if not text:
        # Keep the flag set so the user can try again.
        await update.message.reply_text(
            "That's empty. Send the instructions you want carousels to follow."
        )
        return
    if len(text) > CAROUSEL_INSTRUCTIONS_MAX:
        await update.message.reply_text(
            f"That's {len(text)} characters. Keep it under "
            f"{CAROUSEL_INSTRUCTIONS_MAX} and send again."
        )
        return

    user_id = update.effective_user.id
    user_data = load_user(user_id) or {}
    user_data.setdefault("custom_instructions", {})["carousel"] = text
    save_user(user_id, user_data)
    context.user_data.pop("awaiting_carousel_instructions", None)

    await update.message.reply_text(
        "✅ Saved. Your next carousels will follow these."
    )


# ----------------------------------------------------------------------
# Autopost settings: per-platform toggles (Instagram / Facebook).
# ----------------------------------------------------------------------

_PLATFORM_DISPLAY = {"instagram": "Instagram", "facebook": "Facebook"}


@require_auth
async def autopost_settings_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show the two platform toggles + connection state, plus connect
    entries for any platform not yet connected."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    ap = get_autopost(load_user(user_id))
    ig_conn = get_token(user_id) is not None
    fb_conn = get_fb_token(user_id) is not None

    def _label(emoji: str, name: str, on: bool, conn: bool) -> str:
        state = "ON ✅" if on else "OFF"
        suffix = "" if conn else " (not connected)"
        return f"{emoji} {name}: {state}{suffix}"

    keyboard = [
        [InlineKeyboardButton(
            _label("📷", "Instagram", ap["instagram"], ig_conn),
            callback_data="autopost_toggle_ig",
        )],
        [InlineKeyboardButton(
            _label("📘", "Facebook", ap["facebook"], fb_conn),
            callback_data="autopost_toggle_fb",
        )],
    ]
    if not ig_conn:
        keyboard.append([InlineKeyboardButton(
            "🔗 Connect Instagram", callback_data="settings_connect_ig",
        )])
    if not fb_conn:
        keyboard.append([InlineKeyboardButton(
            "🔗 Connect Facebook", callback_data="connect_facebook",
        )])
    keyboard.append([InlineKeyboardButton("← Back", callback_data="main_settings")])

    text = (
        "📤 Autopost settings\n\n"
        "Choose where your carousels publish. A platform must be connected "
        "before you can turn it on. Both can be on at once; if one fails, the "
        "other still posts."
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


@require_auth
async def autopost_toggle_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Flip one platform toggle. Refuses to enable a platform that has no
    stored token (guides the user to connect first)."""
    query = update.callback_query
    user_id = update.effective_user.id
    platform = "instagram" if query.data == "autopost_toggle_ig" else "facebook"

    user_data = load_user(user_id)
    if user_data is None:
        await query.answer("No account info. Please /start first.", show_alert=True)
        return

    ap = get_autopost(user_data)
    connected = (
        get_token(user_id) is not None if platform == "instagram"
        else get_fb_token(user_id) is not None
    )

    if not ap[platform] and not connected:
        await query.answer(
            f"Connect {_PLATFORM_DISPLAY[platform]} first.", show_alert=True,
        )
        await autopost_settings_show(update, context)
        return

    set_autopost(user_data, platform, not ap[platform])
    save_user(user_id, user_data)
    await autopost_settings_show(update, context)


@require_auth
async def facebook_connect_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Connect-Facebook screen. Mirrors instagram_connect_show: mint a
    single-use state, build the FB authorize URL, present it as a button."""
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()
    already = get_fb_token(user_id)

    try:
        state = issue_state(user_id)
        authorize_url = fb_build_authorize_url(state)
    except Exception:
        logger.exception("Failed to build Facebook authorize URL for user_id=%s", user_id)
        await query.edit_message_text(
            "Facebook isn't configured on this bot yet. Check back later.",
        )
        return

    if already:
        page = already.get("page_name") or already.get("page_id", "unknown")
        text = (
            "📘 Facebook is connected.\n\n"
            f"Page: {page}\n\n"
            "Tap below to reconnect (e.g. to switch Page)."
        )
        button_label = "🔄 Reconnect Facebook"
    else:
        text = (
            "📘 Connect your Facebook Page.\n\n"
            "Tap below, approve the app and grant Page access, and you'll be "
            "sent back to a confirmation page. Return here when done."
        )
        button_label = "Open Facebook authorize page"

    keyboard = [
        [InlineKeyboardButton(button_label, url=authorize_url)],
        [InlineKeyboardButton("← Back", callback_data="autopost_settings")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

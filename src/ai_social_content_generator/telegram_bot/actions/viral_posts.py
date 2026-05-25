import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import (
    MAX_VIRAL_KEYWORDS,
    add_viral_keyword,
    load_user,
    remove_viral_keyword,
    save_user,
)
from ai_social_content_generator.ingestion.instagram_scraper import (
    build_viral_excel,
    invalidate_viral_cache,
    scrape_and_process_viral_keywords,
    viral_excel_path,
)

logger = logging.getLogger(__name__)


@require_auth
async def viral_submenu_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_id = update.effective_user.id
    user_data = load_user(user_id)
    keywords = user_data.get("viral_keywords", []) if user_data else []

    header = (
        f"🔥 Viral Posts Research\n\n"
        f"Keywords ({len(keywords)}/{MAX_VIRAL_KEYWORDS}):\n"
    )
    if not keywords:
        body = "No keywords yet. Add some to start researching."
    else:
        body = "\n".join(f"{i + 1}. {kw['text']}" for i, kw in enumerate(keywords))
    text = header + body

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("➕ Add keyword", callback_data="viral_add")],
    ]
    if keywords:
        keyboard.append(
            [InlineKeyboardButton("🗑️ Remove keyword", callback_data="viral_remove")]
        )
        keyboard.append(
            [InlineKeyboardButton("📊 Generate report", callback_data="viral_generate")]
        )
        keyboard.append(
            [InlineKeyboardButton(
                "🔄 Refresh data (clear cache)", callback_data="viral_refresh"
            )]
        )
    keyboard.append([InlineKeyboardButton("← Back", callback_data="viral_back")])

    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query is not None:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=markup,
        )


@require_auth
async def viral_submenu_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "viral_add":
        context.user_data["awaiting_viral_keyword"] = True
        await query.edit_message_text(
            "Send the keyword you want to research (Hebrew or English).\n\n"
            "Examples: 'זוגיות עסקית', 'couples in business', 'marriage and money'"
        )
    elif query.data == "viral_remove":
        await viral_remove_show(update, context)
    elif query.data == "viral_generate":
        await viral_generate_report(update, context)
    elif query.data == "viral_refresh":
        await viral_refresh_cache(update, context)
    elif query.data == "viral_back":
        from ai_social_content_generator.telegram_bot.actions.menu import (
            _main_menu_keyboard,
        )
        await query.edit_message_text(
            "What would you like to do?",
            reply_markup=_main_menu_keyboard(),
        )


async def viral_receive_keyword(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Called from message_bot when awaiting_viral_keyword is True."""
    keyword = update.message.text.strip()
    user_id = update.effective_user.id
    user_data = load_user(user_id)

    if user_data is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No account info. Please complete onboarding first.",
        )
        context.user_data.pop("awaiting_viral_keyword", None)
        return

    result = add_viral_keyword(user_data, keyword)
    if result is None:
        existing_count = len(user_data.get("viral_keywords", []))
        if existing_count >= MAX_VIRAL_KEYWORDS:
            msg = (
                f"Cap reached ({MAX_VIRAL_KEYWORDS} keywords max). "
                f"Remove one first."
            )
        else:
            msg = "Duplicate or empty keyword. Try a different one."
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=msg
        )
    else:
        save_user(user_id, user_data)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Added: {result['text']}",
        )

    context.user_data.pop("awaiting_viral_keyword", None)
    await viral_submenu_show(update, context)


@require_auth
async def viral_remove_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    user_data = load_user(user_id)
    keywords = user_data.get("viral_keywords", []) if user_data else []

    if not keywords:
        keyboard = [[InlineKeyboardButton("← Back", callback_data="viral_back_submenu")]]
        await query.edit_message_text(
            "No keywords to remove.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    lines = [f"{i + 1}. {kw['text']}" for i, kw in enumerate(keywords)]
    text = "Tap a number to remove:\n\n" + "\n".join(lines)

    buttons = [
        InlineKeyboardButton(
            str(i + 1), callback_data=f"viral_remove_pick_{kw['id']}"
        )
        for i, kw in enumerate(keywords)
    ]
    keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    keyboard.append([InlineKeyboardButton("← Back", callback_data="viral_back_submenu")])

    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


@require_auth
async def viral_remove_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    keyword_id = query.data.removeprefix("viral_remove_pick_")
    user_data = load_user(user_id)
    if user_data is None:
        await query.edit_message_text("No account info found.")
        return

    keywords = user_data.get("viral_keywords", [])
    removed_text: str | None = None
    for kw in keywords:
        if kw.get("id") == keyword_id:
            removed_text = kw.get("text")
            break

    removed = remove_viral_keyword(user_data, keyword_id)
    if removed:
        save_user(user_id, user_data)
        if removed_text:
            invalidate_viral_cache(removed_text)
        logger.info("Removed viral keyword id=%s text=%r", keyword_id, removed_text)

    await viral_submenu_show(update, context)


@require_auth
async def viral_back_submenu_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    await viral_submenu_show(update, context)


async def viral_refresh_cache(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    count = invalidate_viral_cache(None)
    plural = "s" if count != 1 else ""
    await query.edit_message_text(
        f"🔄 Cleared cache for {count} keyword{plural}. "
        f"Next 'Generate report' will scrape fresh."
    )
    await asyncio.sleep(1.5)
    await viral_submenu_show(update, context)


async def viral_generate_report(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    user_data = load_user(user_id)
    keywords = user_data.get("viral_keywords", []) if user_data else []
    handle = (user_data.get("handle") if user_data else None) or str(user_id)

    if not keywords:
        await query.edit_message_text("No keywords yet. Add some first.")
        return

    kw_texts = [kw["text"] for kw in keywords]
    plural = "s" if len(kw_texts) != 1 else ""
    await query.edit_message_text(
        f"🔍 Scraping {len(kw_texts)} keyword{plural}...\n"
        f"This takes ~2 min per keyword if not cached.\n"
        f"Cached results return instantly."
    )

    try:
        results = await asyncio.to_thread(
            scrape_and_process_viral_keywords, kw_texts, False
        )
    except Exception:
        logger.exception("Viral pipeline failed for keywords=%r", kw_texts)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Scraping failed. Try again or check logs.",
        )
        return

    output_path = viral_excel_path(handle)
    try:
        await asyncio.to_thread(build_viral_excel, results, output_path)
    except Exception:
        logger.exception("Viral Excel build failed for handle=%s", handle)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Failed to build Excel file. Try again.",
        )
        return

    try:
        with open(output_path, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename="viral_report.xlsx",
                caption=(
                    f"✅ Viral report\n"
                    f"📊 {len(results)} posts across {len(kw_texts)} keyword{plural}\n"
                    f"🏆 Top by all-time + 🆕 last 30d per keyword"
                ),
            )
        logger.info(
            "Sent viral Excel for handle=%s with %d results",
            handle, len(results),
        )
    except Exception:
        logger.exception("Telegram document send failed for handle=%s", handle)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Excel built but failed to send. Try again.",
        )

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import is_onboarded
from ai_social_content_generator.telegram_bot.actions.profile_skill_creator import analyze_from_vault
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

"""Main menu button handler."""


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    """Returns the main menu keyboard. Single source of truth."""
    keyboard = [
        [InlineKeyboardButton("📊 Analyze my profile", callback_data="menu_analyze")],
        [InlineKeyboardButton("💡 Get post ideas", callback_data="menu_ideas")],
        [InlineKeyboardButton("👥 Competitors", callback_data="menu_competitors")],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="menu_refresh"),
            InlineKeyboardButton("⚙️ Edit niche", callback_data="menu_edit_niche"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


@require_auth
async def menu_popup(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Onboarded user — show main menu
    await update.message.reply_text(
        "What would you like to do?",
        reply_markup=_main_menu_keyboard(),
    )

@require_auth
async def main_menu_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "menu_analyze":
        await query.edit_message_text(
            "Analyzing your profile..."
        )
        await analyze_from_vault(update, context)


    if query.data == "menu_ideas":
        await ideas_submenu_show(update, context)

    if query.data == "menu_refresh":
        await query.edit_message_text("Refresh data coming soon!")

    if query.data == "menu_edit_niche":
        await query.edit_message_text("Edit niche coming soon!")

    if query.data == "menu_competitors":
        await query.edit_message_text("Competitors coming soon!")


@require_auth
async def ideas_submenu_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📜 Carousel post", callback_data="ideas_carousel")],
        [InlineKeyboardButton("🎥 Reel ideas", callback_data="ideas_reel")],
        [InlineKeyboardButton("💭 Just brainstorm", callback_data="ideas_brainstorm")],
        [InlineKeyboardButton("← Back", callback_data="ideas_back")],
    ]
    await query.edit_message_text(
        "What kind of post idea?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def ideas_submenu_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "ideas_carousel":
        await query.edit_message_text("Generating a carousel idea... (~30 sec)")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="(Carousel skill not built yet — coming next)",
        )
    elif query.data == "ideas_reel":
        await query.edit_message_text("🎥 Reel ideas coming soon!")
    elif query.data == "ideas_brainstorm":
        await query.edit_message_text("💭 Brainstorm coming soon!")
    elif query.data == "ideas_back":
        await query.edit_message_text(
            "What would you like to do?",
            reply_markup=_main_menu_keyboard(),
        )

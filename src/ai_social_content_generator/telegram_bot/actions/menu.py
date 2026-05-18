from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import is_onboarded, load_user
from ai_social_content_generator.telegram_bot.actions.profile_skill_creator import analyze_from_vault
from ai_social_content_generator.telegram_bot.actions.compose_carousel import compose_carousel_from_vault
from ai_social_content_generator.telegram_bot.actions.competitors import remove_competitor
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
        await competitors_submenu_show(update, context)


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
        await query.edit_message_text("Generating, ~30 sec...")
        await compose_carousel_from_vault(update, context)
    elif query.data == "ideas_reel":
        await query.edit_message_text("🎥 Reel ideas coming soon!")
    elif query.data == "ideas_brainstorm":
        await query.edit_message_text("💭 Brainstorm coming soon!")
    elif query.data == "ideas_back":
        await query.edit_message_text(
            "What would you like to do?",
            reply_markup=_main_menu_keyboard(),
        )

@require_auth
async def competitors_submenu_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user_data = load_user(user_id)
    competitors = user_data.get("competitors", []) if user_data else []

    if not competitors:
        list_text = "No competitors added yet."
    else:
        list_text = "\n".join(f"{i+1}. @{h}" for i, h in enumerate(competitors))

    keyboard = [
        [
            InlineKeyboardButton("➕ Add Competitor", callback_data="competitor_add"),
            InlineKeyboardButton("➖ Remove Competitor", callback_data="competitor_remove"),
        ],
        [InlineKeyboardButton("← Back", callback_data="competitor_back")],
    ]

    await query.edit_message_text(
        f"👥 Your Competitors:\n\n{list_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )



@require_auth
async def competitors_submenu_route(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    if query.data.startswith("competitor_rm_"):
        index_str = query.data.removeprefix("competitor_rm_")
        try:
            index = int(index_str)
        except ValueError:
            return
        remove_competitor(user_id, index)
        await competitors_submenu_show(update, context)
        return

    if query.data == "competitor_remove":
        user_data = load_user(user_id)
        competitors = user_data.get("competitors", []) if user_data else []

        if not competitors:
            keyboard = [[InlineKeyboardButton("← Back", callback_data="competitor_back")]]
            await query.edit_message_text(
                "No competitors to remove.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        buttons = [
            InlineKeyboardButton(str(i + 1), callback_data=f"competitor_rm_{i}")
            for i in range(len(competitors))
        ]
        keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
        keyboard.append([InlineKeyboardButton("← Back", callback_data="competitor_back")])

        await query.edit_message_text(
            "Tap a number to remove:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data == "competitor_back":
        await query.edit_message_text(
            "What would you like to do?",
            reply_markup=_main_menu_keyboard(),
        )
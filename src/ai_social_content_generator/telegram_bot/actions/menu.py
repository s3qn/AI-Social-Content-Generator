from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import is_onboarded, load_user, save_user
from ai_social_content_generator.telegram_bot.actions.profile_skill_creator import analyze_from_vault
from ai_social_content_generator.telegram_bot.actions.competitors import remove_competitor
from ai_social_content_generator.telegram_bot.actions.brainstorm_topics import brainstorm_topics_from_vault, brainstorm_own_process
from ai_social_content_generator.telegram_bot.actions.content_picker import content_picker_entry, reel_format_picker_show
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
        [InlineKeyboardButton("💭 Brainstorm", callback_data="ideas_brainstorm")],
        [InlineKeyboardButton("🎥 Reel ideas", callback_data="ideas_reel")],
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
        await content_picker_entry(update, context, "carousel")
    elif query.data == "ideas_reel":
        await reel_format_picker_show(update, context)
    elif query.data == "ideas_brainstorm":
        await brainstorm_submenu_show(update, context)
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


@require_auth
async def brainstorm_submenu_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user_data = load_user(user_id)
    topics = user_data.get("topics", []) if user_data else []

    if not topics:
        message = "💭 Your Topics:\n\nNo topics yet."
    else:
        lines = []
        for i, topic in enumerate(topics, start=1):
            core = topic.get("core_idea", "")
            headlines_count = len(topic.get("headlines", []))
            if headlines_count > 0:
                marker = f" ({headlines_count} headlines)"
            else:
                marker = ""
            lines.append(f"{i}. {core}{marker}")
        message = "💭 Your Topics:\n\n" + "\n".join(lines)

    keyboard = [
        [InlineKeyboardButton("➕ Brainstorm new ideas", callback_data="brainstorm_new")],
        [InlineKeyboardButton("🗑️ Remove topic", callback_data="brainstorm_remove")],
        [InlineKeyboardButton("⚠️ Remove all", callback_data="brainstorm_remove_all")],
        [InlineKeyboardButton("← Back", callback_data="brainstorm_back")],
    ]

    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def brainstorm_submenu_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    if query.data.startswith("brainstorm_rm_"):
        index_str = query.data.removeprefix("brainstorm_rm_")
        try:
            index = int(index_str)
        except ValueError:
            return
        user_data = load_user(user_id)
        topics = user_data.get("topics", []) if user_data else []
        if 0 <= index < len(topics):
            topics.pop(index)
            save_user(user_id, user_data)
        await brainstorm_submenu_show(update, context)
        return

    if query.data == "brainstorm_new":
        await brainstorm_source_show(update, context)

    elif query.data == "brainstorm_source_auto":
        await brainstorm_topics_from_vault(update, context)

    elif query.data == "brainstorm_own_polish":
        idea = context.user_data.get("pending_own_idea", "")
        await brainstorm_own_process(update, context, idea, mode="polish")

    elif query.data == "brainstorm_own_expand":
        idea = context.user_data.get("pending_own_idea", "")
        await brainstorm_own_process(update, context, idea, mode="expand")

    elif query.data == "brainstorm_remove":
        await brainstorm_remove_buttons(update, context)

    elif query.data == "brainstorm_remove_all":
        await brainstorm_remove_all_confirm(update, context)

    elif query.data == "brainstorm_remove_all_yes":
        user_data = load_user(user_id)
        if user_data is not None:
            user_data["topics"] = []
            save_user(user_id, user_data)
        await brainstorm_submenu_show(update, context)

    elif query.data == "brainstorm_remove_all_no":
        await brainstorm_submenu_show(update, context)

    elif query.data == "brainstorm_back":
        await ideas_submenu_show(update, context)


@require_auth
async def brainstorm_remove_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    user_id = update.effective_user.id
    user_data = load_user(user_id)
    topics = user_data.get("topics", []) if user_data else []

    if not topics:
        keyboard = [[InlineKeyboardButton("← Back", callback_data="brainstorm_back")]]
        await query.edit_message_text(
            "No topics to remove.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    buttons = [
        InlineKeyboardButton(str(i + 1), callback_data=f"brainstorm_rm_{i}")
        for i in range(len(topics))
    ]
    keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    keyboard.append([InlineKeyboardButton("← Back", callback_data="brainstorm_back")])

    await query.edit_message_text(
        "Tap a number to remove:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def brainstorm_source_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    keyboard = [
        [InlineKeyboardButton("🤖 Auto-generate from profile", callback_data="brainstorm_source_auto")],
        [InlineKeyboardButton("✍️ Write my own idea", callback_data="brainstorm_source_own")],
        [InlineKeyboardButton("← Back", callback_data="brainstorm_back")],
    ]

    await query.edit_message_text(
        "How do you want to brainstorm?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def brainstorm_remove_all_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    user_id = update.effective_user.id
    user_data = load_user(user_id)
    topics = user_data.get("topics", []) if user_data else []
    count = len(topics)

    if count == 0:
        keyboard = [[InlineKeyboardButton("← Back", callback_data="brainstorm_back")]]
        await query.edit_message_text(
            "No topics to delete.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    keyboard = [
        [InlineKeyboardButton("⚠️ Yes, delete all", callback_data="brainstorm_remove_all_yes")],
        [InlineKeyboardButton("← Cancel", callback_data="brainstorm_remove_all_no")],
    ]
    await query.edit_message_text(
        f"Delete all {count} topics? This cannot be undone.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
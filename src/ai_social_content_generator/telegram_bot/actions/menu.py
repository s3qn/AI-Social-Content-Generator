from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import is_onboarded
from ai_social_content_generator.telegram_bot.actions.profile_skill_creator import analyze_from_vault
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

"""Main menu button handler."""

@require_auth
async def menu_popup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    # Onboarded user — show main menu
    keyboard = [[
        InlineKeyboardButton("📊 Analyze my profile", callback_data="menu_analyze"),
    ]]
    await update.message.reply_text(
        "What would you like to do?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

@require_auth
async def analyze_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "menu_analyze":
        await query.edit_message_text(
            "Analyzing your profile..."
        )
        await analyze_from_vault(update, context)
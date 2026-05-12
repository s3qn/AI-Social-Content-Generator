from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import is_onboarded
from ai_social_content_generator.telegram_bot.actions.menu import menu_popup
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

##########################
# Message Bot
#
# When a user types any input to the bot, the bot will pass it into claude and claude will message back, will change it as time goes
#############################

@require_auth
async def message_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_onboarded(user_id):
        await update.message.reply_text(
            "Please tap /start to set up your account first."
        )
        return
    
    await menu_popup(update, context)


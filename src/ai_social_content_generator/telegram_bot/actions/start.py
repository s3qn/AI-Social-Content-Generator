from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ConversationHandler
from ai_social_content_generator.telegram_bot.users import is_onboarded
from ai_social_content_generator.telegram_bot.auth import USER_WHITELIST
from ai_social_content_generator.telegram_bot.actions.onboarding import WAITING_FOR_HANDLE


async def start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    if user_id not in USER_WHITELIST:
        await update.message.reply_text("Sorry, Please try again later")
        return ConversationHandler.END
    
    if is_onboarded(user_id):
        await update.message.reply_text("WELCOME TO MY APP!!!!")
        return ConversationHandler.END

    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello, I am Stella, your social media assistant to boost your social media presence by 10x!!!\n\nLet's get you onboarded, please send me your instagram handle to get started:\nFORMAT: '[Handle] or @[Handle] (e.g. @nasa/nasa)'")
    return WAITING_FOR_HANDLE
import logging
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ConversationHandler
from dotenv import load_dotenv, find_dotenv
from ai_social_content_generator.telegram_bot.actions import start_bot, receive_handle, confirm_handle, receive_niche, confirm_niche, cancel, profile_analyzer, message_bot, WAITING_FOR_HANDLE, CONFIRMING_HANDLE, WAITING_FOR_NICHE, CONFIRMING_NICHE

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def load_telegram_bot_token():

    load_dotenv(find_dotenv())
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    return telegram_token

# Main Guard
if __name__ == '__main__':

    token = load_telegram_bot_token()
    application = ApplicationBuilder().token(token).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_bot)],
        states={
            WAITING_FOR_HANDLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_handle)],
            CONFIRMING_HANDLE: [CallbackQueryHandler(confirm_handle)],
            WAITING_FOR_NICHE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_niche)],
            CONFIRMING_NICHE: [CallbackQueryHandler(confirm_niche)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    application.add_handler(conv_handler)

    analyze_handler = CommandHandler('analyze', profile_analyzer)
    message_handle = MessageHandler(filters.TEXT & ~filters.COMMAND, message_bot)
    
    application.add_handler(message_handle)
    application.add_handler(analyze_handler)
    application.run_polling()


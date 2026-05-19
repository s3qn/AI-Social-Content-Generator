import logging
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ConversationHandler
from dotenv import load_dotenv, find_dotenv
from ai_social_content_generator.telegram_bot.actions import start_bot, receive_handle, confirm_handle, receive_niche, confirm_niche, cancel, profile_analyzer, message_bot, WAITING_FOR_HANDLE, CONFIRMING_HANDLE, WAITING_FOR_NICHE, CONFIRMING_NICHE
from ai_social_content_generator.telegram_bot.actions.menu import main_menu_route, ideas_submenu_route, competitors_submenu_route, brainstorm_submenu_route
from ai_social_content_generator.telegram_bot.actions.competitors import (
    competitor_add_start,
    competitor_receive_handle,
    WAITING_FOR_COMPETITOR_HANDLE,
)

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

    competitor_add_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(competitor_add_start, pattern="^competitor_add$")
        ],
        states={
            WAITING_FOR_COMPETITOR_HANDLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, competitor_receive_handle)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(competitor_add_handler)

    analyze_handler = CommandHandler('analyze', profile_analyzer)
    message_handle = MessageHandler(filters.TEXT & ~filters.COMMAND, message_bot)
    menu_analyze = CallbackQueryHandler(main_menu_route, pattern="^menu_")

    application.add_handler(message_handle)
    application.add_handler(analyze_handler)
    application.add_handler(menu_analyze)
    application.add_handler(
        CallbackQueryHandler(ideas_submenu_route, pattern="^ideas_")
    )
    application.add_handler(
        CallbackQueryHandler(competitors_submenu_route, pattern= "^competitor_")
    )
    application.add_handler(
        CallbackQueryHandler(brainstorm_submenu_route, pattern="^brainstorm_")
    )
    application.run_polling()


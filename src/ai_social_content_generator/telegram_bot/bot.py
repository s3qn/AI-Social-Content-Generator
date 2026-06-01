import logging
import os
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ConversationHandler
from dotenv import load_dotenv, find_dotenv
from ai_social_content_generator.telegram_bot.actions import start_bot, receive_handle, confirm_handle, receive_niche, confirm_niche, cancel, profile_analyzer, message_bot, WAITING_FOR_HANDLE, CONFIRMING_HANDLE, WAITING_FOR_NICHE, CONFIRMING_NICHE
from ai_social_content_generator.telegram_bot.actions import own_idea_start, own_idea_receive, WAITING_FOR_OWN_IDEA
from ai_social_content_generator.telegram_bot.actions.menu import main_menu_route, ideas_submenu_route, competitors_submenu_route, brainstorm_submenu_route
from ai_social_content_generator.telegram_bot.actions.content_picker import (
    topic_picker_route,
    headline_picker_route,
    topic_picker_back_route,
    reel_format_picker_route,
)
from ai_social_content_generator.telegram_bot.actions.competitors import (
    competitor_add_start,
    competitor_receive_handle,
    WAITING_FOR_COMPETITOR_HANDLE,
)
from ai_social_content_generator.telegram_bot.actions.viral_posts import (
    viral_submenu_route,
    viral_remove_route,
    viral_back_submenu_route,
)
from ai_social_content_generator.telegram_bot.actions.settings import (
    settings_submenu_route,
    scheduler_submenu_route,
)
from ai_social_content_generator.telegram_bot.scheduler import (
    rebuild_all_reminders_on_startup,
)
from ai_social_content_generator.telegram_bot.actions.admin import (
    status_command,
    broadcast_command,
    restart_command,
    testschedule_command,
    set_bot_start_time,
)
from ai_social_content_generator.telegram_bot.actions.morning_ideas import (
    morning_idea_route,
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

    set_bot_start_time(time.time())

    token = load_telegram_bot_token()
    application = (
        ApplicationBuilder()
        .token(token)
        .concurrent_updates(True)
        .post_init(rebuild_all_reminders_on_startup)
        .build()
    )
    
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

    own_idea_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(own_idea_start, pattern="^brainstorm_source_own$")
        ],
        states={
            WAITING_FOR_OWN_IDEA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, own_idea_receive)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(own_idea_handler)

    analyze_handler = CommandHandler('analyze', profile_analyzer)
    message_handle = MessageHandler(filters.TEXT & ~filters.COMMAND, message_bot)
    menu_analyze = CallbackQueryHandler(main_menu_route, pattern=r"^(menu_|viral_menu$|main_settings$)")

    application.add_handler(message_handle)
    application.add_handler(analyze_handler)
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("restart", restart_command))
    application.add_handler(CommandHandler("testschedule", testschedule_command))
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
    application.add_handler(
        CallbackQueryHandler(topic_picker_back_route, pattern="^topic_picker_back$")
    )
    application.add_handler(
        CallbackQueryHandler(topic_picker_route, pattern="^topic_pick_")
    )
    application.add_handler(
        CallbackQueryHandler(headline_picker_route, pattern="^headline_pick_")
    )
    application.add_handler(
        CallbackQueryHandler(reel_format_picker_route, pattern="^reel_format_")
    )
    application.add_handler(
        CallbackQueryHandler(
            viral_submenu_route,
            pattern=r"^viral_(add|remove|generate|refresh|back)$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(viral_remove_route, pattern=r"^viral_remove_pick_")
    )
    application.add_handler(
        CallbackQueryHandler(viral_back_submenu_route, pattern=r"^viral_back_submenu$")
    )
    application.add_handler(
        CallbackQueryHandler(
            settings_submenu_route,
            pattern=r"^settings_(edit_niche|scheduler|back)$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            scheduler_submenu_route,
            pattern=r"^scheduler_(set_morning|set_evening|set_off|back)$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(morning_idea_route, pattern=r"^idea_pick_")
    )
    application.run_polling()


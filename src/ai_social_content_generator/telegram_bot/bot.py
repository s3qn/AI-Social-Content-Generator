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
    headline_mode_route,
    headline_regen_route,
    topic_picker_back_route,
    reel_format_picker_route,
)
from ai_social_content_generator.telegram_bot.actions.reel_formats_ui import (
    reel_format_add_start,
    format_save,
    format_regen,
    format_discard,
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
    viral_add_route,
    viral_keep_asis_route,
    viral_excel_route,
    viral_view_route,
    viral_transcript_route,
    viral_hooks_route,
    viral_hookadd_route,
    viral_format_route,
)
from ai_social_content_generator.telegram_bot.actions.settings import (
    settings_submenu_route,
    scheduler_submenu_route,
    receive_background_photo,
    receive_logo_document,
    customize_submenu_route,
    carousel_instructions_show,
    carousel_instr_edit,
    carousel_instr_clear,
    autopost_settings_show,
    autopost_toggle_route,
    facebook_connect_show,
)
from ai_social_content_generator.telegram_bot.scheduler import (
    rebuild_all_reminders_on_startup,
)
from ai_social_content_generator.telegram_bot.actions.scheduled_posts import (
    scheduled_posts_show,
    scheduled_cancel_route,
    rebuild_scheduled_posts_on_startup,
)
from ai_social_content_generator.instagram.callback_server import (
    start_callback_server,
)
from ai_social_content_generator.instagram.refresh import (
    schedule_token_refresh_job,
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
    morning_idea_format_route,
)
from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
    generate_carousel_images,
    carousel_individual_route,
    carousel_publish_route,
    carousel_postnow_route,
    carousel_schedule_route,
    carousel_confirm_route,
    carousel_cancel_route,
    carousel_edit_show,
    carousel_edit_slide_route,
    carousel_edit_cancel_route,
    slide_remove_show,
    slide_remove_route,
    slide_add_show,
    slide_add_route,
    carousel_makereel_route,
    carousel_makereel_format_route,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def load_telegram_bot_token():

    load_dotenv(find_dotenv())
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    return telegram_token


async def _on_startup(application):
    """post_init: runs after PTB init, before polling. We piggyback the
    OAuth callback server, the daily IG token-refresh job, and the
    existing reminder rebuild here so they all share PTB's event loop."""
    await rebuild_all_reminders_on_startup(application)
    await rebuild_scheduled_posts_on_startup(application)
    schedule_token_refresh_job(application)
    port = int(os.getenv("OAUTH_CALLBACK_PORT", "8081"))
    runner = await start_callback_server(port)
    # Keep a reference so the runner isn't GC'd while the bot is alive.
    application.bot_data["_oauth_callback_runner"] = runner

# Main Guard
if __name__ == '__main__':

    set_bot_start_time(time.time())

    token = load_telegram_bot_token()
    application = (
        ApplicationBuilder()
        .token(token)
        .concurrent_updates(True)
        .post_init(_on_startup)
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
        CallbackQueryHandler(headline_mode_route, pattern=r"^headline_mode_(ai|own)$")
    )
    application.add_handler(
        CallbackQueryHandler(headline_regen_route, pattern=r"^headline_regen$")
    )
    # MUST register before the generic reel_format_ picker route below,
    # else "reel_format_add" is parsed as a (nonexistent) format id.
    application.add_handler(
        CallbackQueryHandler(reel_format_add_start, pattern=r"^reel_format_add$")
    )
    application.add_handler(
        CallbackQueryHandler(format_save, pattern=r"^format_save$")
    )
    application.add_handler(
        CallbackQueryHandler(format_regen, pattern=r"^format_regen$")
    )
    application.add_handler(
        CallbackQueryHandler(format_discard, pattern=r"^format_discard$")
    )
    application.add_handler(
        CallbackQueryHandler(reel_format_picker_route, pattern=r"^reel_format_.+$")
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
        CallbackQueryHandler(viral_add_route, pattern=r"^viral_add_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(viral_keep_asis_route, pattern=r"^viral_keep_asis$")
    )
    application.add_handler(
        CallbackQueryHandler(viral_excel_route, pattern=r"^viral_excel$")
    )
    application.add_handler(
        CallbackQueryHandler(viral_view_route, pattern=r"^viral_view_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(viral_transcript_route, pattern=r"^viral_transcript_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(viral_hooks_route, pattern=r"^viral_hooks_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(viral_hookadd_route, pattern=r"^viral_hookadd_\d+_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(viral_format_route, pattern=r"^viral_format_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(
            settings_submenu_route,
            pattern=r"^settings_(edit_niche|scheduler|back|connect_ig|customize)$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            customize_submenu_route,
            pattern=r"^customize_(background|logo|back|rerender)$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            carousel_instructions_show, pattern=r"^carousel_instructions$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            carousel_instr_edit, pattern=r"^carousel_instr_edit$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            carousel_instr_clear, pattern=r"^carousel_instr_clear$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            autopost_settings_show, pattern=r"^autopost_settings$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            autopost_toggle_route, pattern=r"^autopost_toggle_(ig|fb)$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            facebook_connect_show, pattern=r"^connect_facebook$"
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
    application.add_handler(
        CallbackQueryHandler(
            morning_idea_format_route, pattern=r"^(briefpick_|briefreel_)"
        )
    )
    application.add_handler(
        CallbackQueryHandler(generate_carousel_images, pattern=r"^gen_carousel_img$")
    )
    application.add_handler(
        CallbackQueryHandler(
            carousel_individual_route, pattern=r"^gen_carousel_individual$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            carousel_publish_route, pattern=r"^gen_carousel_publish$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            carousel_postnow_route, pattern=r"^gen_carousel_postnow$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            carousel_schedule_route, pattern=r"^gen_carousel_schedule$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            scheduled_posts_show, pattern=r"^scheduled_(posts|back)$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            scheduled_cancel_route, pattern=r"^sched_cancel_[a-f0-9]+$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            carousel_confirm_route, pattern=r"^gen_carousel_confirm$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            carousel_cancel_route, pattern=r"^gen_carousel_cancel$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(carousel_edit_show, pattern=r"^gen_carousel_edit$")
    )
    application.add_handler(
        CallbackQueryHandler(carousel_edit_slide_route, pattern=r"^edit_slide_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(carousel_edit_cancel_route, pattern=r"^edit_cancel$")
    )
    application.add_handler(
        CallbackQueryHandler(slide_remove_show, pattern=r"^slide_remove$")
    )
    application.add_handler(
        CallbackQueryHandler(slide_remove_route, pattern=r"^slide_rm_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(slide_add_show, pattern=r"^slide_add$")
    )
    application.add_handler(
        CallbackQueryHandler(slide_add_route, pattern=r"^slide_ins_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(carousel_makereel_route, pattern=r"^gen_carousel_makereel$")
    )
    application.add_handler(
        CallbackQueryHandler(
            carousel_makereel_format_route, pattern=r"^convert_reel_.+$"
        )
    )
    # Global photo + document handlers — registered LAST so they don't
    # shadow any ConversationHandler media states (there aren't any
    # today, but order is the future-safe default). Both handlers are
    # flag-gated on a per-flow flag in user_data and consume their flag
    # immediately, so stray uploads are silently ignored.
    application.add_handler(MessageHandler(filters.PHOTO, receive_background_photo))
    application.add_handler(MessageHandler(filters.Document.IMAGE, receive_logo_document))
    application.run_polling()


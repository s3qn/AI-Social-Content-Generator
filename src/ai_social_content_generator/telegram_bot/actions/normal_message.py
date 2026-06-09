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

    if context.user_data.get("awaiting_viral_keyword"):
        from ai_social_content_generator.telegram_bot.actions.viral_posts import (
            viral_receive_keyword,
        )
        await viral_receive_keyword(update, context)
        return

    editing = context.user_data.get("editing_slide")
    if editing is not None:
        new_text = (update.message.text or "").strip()
        if not new_text:
            # Empty / whitespace-only: keep the flag set so the user can try again.
            await update.message.reply_text(
                "That's empty — send the corrected text for the slide."
            )
            return

        data = context.user_data.get("last_carousel")
        slides = data.get("slides") if data else None
        if not slides or editing < 1 or editing > len(slides):
            # Stash gone or index out of range: clear the flag and explain.
            context.user_data.pop("editing_slide", None)
            await update.message.reply_text(
                "Couldn't find that carousel anymore. Generate again."
            )
            return

        slides[editing - 1]["text"] = new_text
        context.user_data.pop("editing_slide", None)
        await update.message.reply_text("✏️ Updating slide…")

        # Local import — compose_carousel pulls heavy modules (Playwright,
        # IG SDK). Importing at module top would slow every text message.
        from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
            _rerender_and_send,
        )
        await _rerender_and_send(
            update, context,
            progress_text="🎨 Re-rendering with your edit…",
            success_caption="Slide updated.",
        )
        return

    await menu_popup(update, context)


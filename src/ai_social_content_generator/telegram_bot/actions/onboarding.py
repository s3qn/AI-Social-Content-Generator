from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ConversationHandler

from ai_social_content_generator.ingestion.instagram_scraper import get_profile

####################################################################################################
# Onboarding
# This Phase is for new users using the bot once a new user hits start, the onboarding will begin!
####################################################################################################

WAITING_FOR_HANDLE, CONFIRMING_HANDLE = range(2)

# ===================== GET HANDLE ============================

async def receive_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):

    handle = update.message.text.lstrip("@").strip()

    context.user_data["handle"] = handle

    await update.message.reply_text(
        f"Got it: @{handle}\n\nGive me a moment please..."
    )

    profile = get_profile(handle, limit=1)

    if profile is None:
        await update.message.reply_text("Handle doesn't exist, please type your handle again\nFORMAT: '[Handle] or @[Handle] (e.g. @nasa/nasa)'")
        return WAITING_FOR_HANDLE
    
    bio = profile.get("biography", "(no bio)")
    pic_url = profile.get("profilePicUrl")

    keyboard = [
        [InlineKeyboardButton("✅ Yes", callback_data="handle_yes")],
        [InlineKeyboardButton("❌ No", callback_data="handle_no")],
        [InlineKeyboardButton("Cancel", callback_data="handle_cancel")]
    ]
    await update.message.reply_photo(
        photo=pic_url,
        caption=f"@{handle}\n\n{bio}\n\nIs this you?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    return CONFIRMING_HANDLE


# ===================== CONFIRM HANDLE ============================

async def confirm_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    # This fires when mom taps a button (not when she types text)
    query = update.callback_query
    await query.answer()  # acknowledge the tap
    
    handle = context.user_data["handle"]  # ← here's how we get it
    
    if query.data == "handle_yes":
        await query.edit_message_caption(caption=f"✓ Confirmed @{handle}. (Next step coming...)")
        return ConversationHandler.END  # for now; later → WAITING_FOR_NICHE
    
    elif query.data == "handle_no":
        await query.edit_message_caption(caption="No problem. Send me your handle again:")
        return WAITING_FOR_HANDLE  # back to handle entry
    
    elif query.data == "handle_cancel":
        await query.edit_message_caption(caption="No problem. use /start on onboard again")
        return ConversationHandler.END  # back to handle entry

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Onboarding cancelled.")
    return ConversationHandler.END
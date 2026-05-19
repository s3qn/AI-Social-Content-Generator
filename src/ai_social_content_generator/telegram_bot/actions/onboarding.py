from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ConversationHandler

from ai_social_content_generator.ingestion.instagram_scraper import get_profile
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.users import save_user

####################################################################################################
# Onboarding
# This Phase is for new users using the bot once a new user hits start, the onboarding will begin!
####################################################################################################

WAITING_FOR_HANDLE, CONFIRMING_HANDLE, WAITING_FOR_NICHE, CONFIRMING_NICHE = range(4)

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
        await query.edit_message_caption(caption=f"✓ Confirmed @{handle}.")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="In order for me to help you presicely and generate you solid ideas, i will need your precise niche, please tell me what do you do?\n\nWrite at least 2-3 sentences about what you do (e.g. I help ____ do ____, I am a _____ )")
        return WAITING_FOR_NICHE
    
    elif query.data == "handle_no":
        await query.edit_message_caption(caption="No problem. Send me your handle again:")
        return WAITING_FOR_HANDLE  # back to handle entry
    
    elif query.data == "handle_cancel":
        await query.edit_message_caption(caption="No problem. use /start on onboard again")
        return ConversationHandler.END  # back to handle entry

    return ConversationHandler.END

# ===================== GET NICHE ============================

async def receive_niche(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_input = update.message.text

    context.user_data.setdefault("niche_inputs", []).append(user_input)

    full_message = "\n".join(context.user_data["niche_inputs"])

    await update.message.reply_text(
        f'Thank you, analyzing niche...'
    )

    # Give it to claude
    claude_reply = await message_claude(
        
        prompt=
            f'''
You are helping a content creator clarify their niche.

The user just typed a sentence describing what they do. Your job is to:
1. Detect if their input is gibberish (random letters, nonsense, no words)
2. Detect if their input is too vague to work with (e.g., "I help people", 
   "I do coaching", "social media stuff")
3. Otherwise, produce a clean 1-2 sentence summary of their niche

RESPONSE FORMAT — output EXACTLY one of these three structures:

If gibberish:
STATUS: GIBBERISH

If vague (a real but too-generic answer):
STATUS: VAGUE
FOLLOW_UP: [one clarifying question in the user's language, e.g., 
"What kind of help do you offer? Who are your clients?"]

If clear:
STATUS: OK
SUMMARY: [1-2 sentence summary in the user's language, faithful to what 
they said. Do NOT add facts they didn't mention.]

CRITICAL RULES:
- Match the user's language. If they wrote Hebrew, respond in Hebrew. 
  If English, English.
- For SUMMARY: only use information the user gave you. Don't invent 
  credentials, audience, or specialties.
- For FOLLOW_UP: ask the most useful clarifying question, not generic 
  "tell me more."
- Output ONLY the structured response. No greetings, no "great!", no 
  additional commentary.
- If the input contains both real content and gibberish, focus on the 
  real content. Treat the gibberish as a typo to ignore.

USER'S NICHE DESCRIPTION:
{full_message}

''')
    
    result = claude_reply.stdout

    if "STATUS: GIBBERISH" in result:
        await update.message.reply_text(
            "I didn't understand. Can you describe your niche again?"
            )
        return WAITING_FOR_NICHE

    if "STATUS: VAGUE" in result:
        follow_up = result.split("FOLLOW_UP:")[1].strip()
        await update.message.reply_text(follow_up)
        return WAITING_FOR_NICHE
    
    if "STATUS: OK" in result:
        summary = result.split("SUMMARY:")[1].strip()
        context.user_data["niche_summary"] = summary
        keyboard = [[
        InlineKeyboardButton("✅ Yes", callback_data="niche_yes"),
        InlineKeyboardButton("🔄 Regenerate", callback_data="niche_regen"),
        InlineKeyboardButton("✏️ Edit", callback_data="niche_edit"),
        ]]
    
        await update.message.reply_text(
            f"Your niche:\n\n{summary}\n\nIs this right?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        return CONFIRMING_NICHE

async def confirm_niche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if query.data == "niche_yes":
        handle = context.user_data["handle"]
        niche_summary = context.user_data["niche_summary"]
        
        save_user(user_id, {
            "handle": handle,
            "niche": niche_summary,
        })
        
        await query.edit_message_text(
            f"🎉 Onboarding complete!\n\n"
            f"Handle: @{handle}\n"
            f"Niche: {niche_summary}\n\n"
            f"To open the menu, write any message in the chat and it will open the menu!"
        )
        return ConversationHandler.END
    
    elif query.data == "niche_regen":
        await query.edit_message_text(
            "🔄 Regenerate isn't built yet. Tap Yes to confirm, or use /cancel."
        )
        return CONFIRMING_NICHE  # stay in state, mom can try again
    
    elif query.data == "niche_edit":
        await query.edit_message_text(
            "✏️ Edit isn't built yet. Tap Yes to confirm, or use /cancel."
        )
        return CONFIRMING_NICHE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Onboarding cancelled.")
    return ConversationHandler.END



import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ConversationHandler
from dotenv import load_dotenv, find_dotenv
import subprocess
from pathlib import Path
from ai_social_content_generator.telegram_bot.users import is_onboarded
import json
from ai_social_content_generator.ingestion.instagram_scraper import get_profile
from ai_social_content_generator.telegram_bot.auth import require_auth, USER_WHITELIST

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def message_claude(prompt):
    result = subprocess.run(

        ["claude", "--print", prompt],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result

@require_auth
async def profile_analyzer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    
    if not context.args:
        await update.message.reply_text("Usage: /analyze <handle>")
        return

    handle = context.args[0]
    handle = handle.lstrip("@")

    profile_path = Path(f"cache/{handle}-profile.json")
    posts_path = Path(f"cache/{handle}-posts.json")

    if not profile_path.exists() or not posts_path.exists():

        await update.message.reply_text(f"No cached data for @{handle}, make sure data is cached!")
        return
    
    profile_data = profile_path.read_text(encoding='utf-8')
    posts_data = posts_path.read_text(encoding='utf-8')

    claude_reply = message_claude(

        prompt= f'''
        You are a niche analyzer.

Your task: analyze an Instagram profile to identify niche, audience, voice, 
and recurring themes.

CRITICAL INSTRUCTIONS:
- The bio field is the authoritative source for niche. Trust it.
- Post captions provide evidence of voice and recurring themes ONLY.
- Do NOT redefine the niche based on caption topics.
- If bio and captions seem to contradict, the bio wins.
- Respond in English.
- If data is insufficient, set status to insufficient_data and explain why.

OUTPUT FORMAT (exactly this):
---
skill: analyze_profile
handle: {handle}
status: success
---

## Niche
[1-2 sentences anchored on bio]

## Account Owner
[2-3 sentences, credentials and expertise from bio]

## Target Audience
[2-3 sentences inferred from content]

## Voice
[3-5 descriptors — short adjectives or phrases]

## Recurring Themes
[3-5 bullet points — topics that come up across posts]

PROFILE DATA:
{profile_data}

POSTS DATA:
{posts_data}'''
    )
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=claude_reply.stdout)


def load_telegram_bot_token():

    load_dotenv(find_dotenv())
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    return telegram_token

##############
# Onboarding #
##############

WAITING_FOR_HANDLE, CONFIRMING_HANDLE = range(2)


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

# Detect any message and pass it into claude!

@require_auth
async def message_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    text_from_user = update.message.text
    claude_reply = message_claude(text_from_user)
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=claude_reply.stdout)


# Main Guard
if __name__ == '__main__':


    
    token = load_telegram_bot_token()
    application = ApplicationBuilder().token(token).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_bot)],
        states={
            WAITING_FOR_HANDLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_handle)],
            CONFIRMING_HANDLE: [CallbackQueryHandler(confirm_handle)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    application.add_handler(conv_handler)

    analyze_handler = CommandHandler('analyze', profile_analyzer)
    message_handle = MessageHandler(filters.TEXT & ~filters.COMMAND, message_bot)
    
    application.add_handler(message_handle)
    application.add_handler(analyze_handler)
    application.run_polling()


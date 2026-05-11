import logging
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv, find_dotenv
import subprocess
from functools import wraps
from pathlib import Path

# USER WHITELIST
USER_WHITELIST = [6552355280, ]

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def require_auth(func):
    @wraps(func)
    async def wrapped(update, context):
        if update.effective_user.id not in USER_WHITELIST:
            return
        await func(update, context)
    return wrapped

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

async def start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello, this is a private bot, limited to a specific user, if you came across this bot, you will only be able to see this message.")

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
    
    start_handler = CommandHandler('start', start_bot)
    analyze_handler = CommandHandler('analyze', profile_analyzer)
    message_handle = MessageHandler(filters.TEXT & ~filters.COMMAND, message_bot)
    application.add_handler(start_handler)
    application.add_handler(message_handle)
    application.add_handler(analyze_handler)
    application.run_polling()


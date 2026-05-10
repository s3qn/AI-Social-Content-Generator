import logging
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv, find_dotenv
import subprocess

# USER WHITELIST
user_whitelist = [6552355280]

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

def load_telegram_bot_token():

    load_dotenv(find_dotenv())
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    return telegram_token

async def start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello, this is a private bot, limited to a specific user, if you came across this bot, you will only be able to see this message.")

# Detect any message and pass it into claude!
async def message_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id not in user_whitelist:
        return
    
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
    message_handle = MessageHandler(filters.TEXT & ~filters.COMMAND, message_bot)
    application.add_handler(start_handler)
    application.add_handler(message_handle)
    application.run_polling()


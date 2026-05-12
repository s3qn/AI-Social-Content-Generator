from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from telegram import Update
from telegram.ext import ContextTypes

##########################
# Message Bot
#
# When a user types any input to the bot, the bot will pass it into claude and claude will message back, will change it as time goes
#############################

@require_auth
async def message_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    text_from_user = update.message.text
    claude_reply = message_claude(text_from_user)
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=claude_reply.stdout)

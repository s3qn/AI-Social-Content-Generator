from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.actions import message_claude
from telegram import Update
from telegram.ext import ContextTypes
from pathlib import Path


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


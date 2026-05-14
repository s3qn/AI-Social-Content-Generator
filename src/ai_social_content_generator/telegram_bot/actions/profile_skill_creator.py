from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.users import load_user
from telegram import Update
from telegram.ext import ContextTypes
from pathlib import Path


async def _run_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE, handle: str, niche = str | None == None):

    handle = handle.lstrip("@")

    profile_path = Path(f"cache/{handle}-profile.json")
    posts_path = Path(f"cache/{handle}-posts.json")

    if not profile_path.exists() or not posts_path.exists():

        await update.message.reply_text(f"No cached data for @{handle}, make sure data is cached!")
        return

    profile_data = profile_path.read_text(encoding='utf-8')
    posts_data = posts_path.read_text(encoding='utf-8')

    if niche:
        prompt = build_prompt_with_niche(handle, niche, profile_data, posts_data)
    else:
        prompt = build_prompt_with_bio(handle, profile_data, posts_data)

    claude_reply = message_claude(prompt)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=claude_reply.stdout)

@require_auth
async def profile_analyzer(update: Update, context: ContextTypes.DEFAULT_TYPE):


    if not context.args:
        await update.message.reply_text("Usage: /analyze <handle>")
        return

    await _run_analysis(update, context, context.args[0])


@require_auth
async def analyze_from_vault(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reads handle from vault and runs analysis. Called from menu button."""
    user_id = update.effective_user.id
    user_data = load_user(user_id)



    if user_data is None or "handle" not in user_data:
        await update.message.reply_text("No handle found in your account. Please onboard first.")
        return

    handle = user_data["handle"]
    niche = user_data.get("niche")

    await _run_analysis(update, context, handle, niche)


def build_prompt_with_bio(handle, posts_data, profile_data):

    return f'''
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

def build_prompt_with_niche(handle, niche, profile_data, posts_data):

    return f'''You are analyzing an Instagram account on behalf of its owner.

The account owner has stated their niche as:
"{niche}"

Treat this niche as authoritative ground truth. Do NOT redetermine or
contradict the niche based on bio or caption content. Your job is to
analyze HOW this account expresses this niche through audience, voice,
and themes.

CRITICAL INSTRUCTIONS:
- Niche section: state the user's niche above, do NOT infer a different one.
- Even if posts discuss topics that suggest a different specialty, the
  stated niche wins.
- Caption topics are evidence of voice/themes, not niche.
- Respond in English.
- If data is insufficient for audience/voice/themes, say so.

OUTPUT FORMAT (exactly this):
---
skill: analyze_profile
handle: {handle}
status: success
niche_source: user_provided
---

## Niche
{niche}

## Account Owner
[2-3 sentences from bio — credentials, expertise]

## Target Audience
[2-3 sentences inferred from content + the stated niche]

## Voice
[3-5 short descriptors]

## Recurring Themes
[3-5 bullet points — actual recurring topics]

PROFILE DATA:
{profile_data}

POSTS DATA:
{posts_data}'''

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.users import load_user
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def _run_analysis(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    handle: str,
    niche: str | None = None,
) -> None:

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
    raw_output = getattr(claude_reply, "stdout", None)

    if not raw_output:
        logger.error("Claude returned no output for handle=%s reply=%r", handle, claude_reply)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Analysis failed, try again.",
        )
        return

    analysis = _parse_analysis_json(raw_output)

    if analysis is None:
        logger.error("Failed to parse Claude JSON for handle=%s. Raw output: %s", handle, raw_output)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Analysis failed, try again.",
        )
        return

    analysis["handle"] = handle
    analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()

    _save_analysis(handle, analysis)

    summary = _format_summary(analysis)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=summary)


@require_auth
async def profile_analyzer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    if not context.args:
        await update.message.reply_text("Usage: /analyze <handle>")
        return

    await _run_analysis(update, context, context.args[0])


@require_auth
async def analyze_from_vault(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reads handle from vault and runs analysis. Called from menu button."""
    user_id = update.effective_user.id
    user_data = load_user(user_id)

    if user_data is None or "handle" not in user_data:
        await update.message.reply_text("No handle found in your account. Please onboard first.")
        return

    handle = user_data["handle"]
    niche = user_data.get("niche")

    await _run_analysis(update, context, handle, niche)


def _parse_analysis_json(raw: str) -> dict | None:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _save_analysis(handle: str, analysis: dict) -> None:
    out_path = Path(f"cache/{handle}-analysis.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _format_summary(analysis: dict) -> str:
    handle = analysis.get("handle", "")
    niche = analysis.get("niche", "—")
    niche_source = analysis.get("niche_source", "")
    owner = analysis.get("account_owner", "—")
    audience = analysis.get("target_audience", "—")
    voice = analysis.get("voice", [])
    themes = analysis.get("recurring_themes", [])

    if niche_source == "user_provided":
        source_label = " (your stated niche)"
    elif niche_source == "inferred_from_bio":
        source_label = " (inferred from bio)"
    else:
        source_label = ""

    voice_str = ", ".join(voice) if isinstance(voice, list) else str(voice)
    if isinstance(themes, list):
        themes_str = "\n".join(f"• {t}" for t in themes)
    else:
        themes_str = str(themes)

    return (
        f"📊 Analysis for @{handle}\n\n"
        f"Niche{source_label}:\n{niche}\n\n"
        f"Account Owner:\n{owner}\n\n"
        f"Target Audience:\n{audience}\n\n"
        f"Voice: {voice_str}\n\n"
        f"Recurring Themes:\n{themes_str}"
    )


def build_prompt_with_bio(handle: str, profile_data: str, posts_data: str) -> str:

    return f'''You are a niche analyzer.

Your task: analyze an Instagram profile to identify niche, audience, voice,
and recurring themes.

CRITICAL INSTRUCTIONS:
- The bio field is the authoritative source for niche. Trust it.
- Post captions provide evidence of voice and recurring themes ONLY.
- Do NOT redefine the niche based on caption topics.
- If bio and captions seem to contradict, the bio wins.
- Respond in English.

OUTPUT FORMAT:
Return ONLY a single valid JSON object. No markdown fences, no prose
before or after. The object must have exactly these keys:

{{
  "handle": "{handle}",
  "niche": "<1-2 sentences anchored on bio>",
  "niche_source": "inferred_from_bio",
  "account_owner": "<2-3 sentences: credentials and expertise from bio>",
  "target_audience": "<2-3 sentences inferred from content>",
  "voice": ["<descriptor>", "<descriptor>", "<descriptor>"],
  "recurring_themes": ["<theme>", "<theme>", "<theme>"],
  "analyzed_at": "<ISO 8601 timestamp>"
}}

- voice: array of 3-5 short adjectives or phrases.
- recurring_themes: array of 3-5 topics that come up across posts.
- niche_source must be exactly "inferred_from_bio".

PROFILE DATA:
{profile_data}

POSTS DATA:
{posts_data}'''


def build_prompt_with_niche(handle: str, niche: str, profile_data: str, posts_data: str) -> str:

    return f'''You are analyzing an Instagram account on behalf of its owner.

The account owner has stated their niche as:
"{niche}"

Treat this niche as authoritative ground truth. Do NOT redetermine or
contradict the niche based on bio or caption content. Your job is to
analyze HOW this account expresses this niche through audience, voice,
and themes.

CRITICAL INSTRUCTIONS:
- niche field: use the user's stated niche above, do NOT infer a different one.
- Even if posts discuss topics that suggest a different specialty, the
  stated niche wins.
- Caption topics are evidence of voice/themes, not niche.
- Respond in English.

OUTPUT FORMAT:
Return ONLY a single valid JSON object. No markdown fences, no prose
before or after. The object must have exactly these keys:

{{
  "handle": "{handle}",
  "niche": "{niche}",
  "niche_source": "user_provided",
  "account_owner": "<2-3 sentences: credentials and expertise from bio>",
  "target_audience": "<2-3 sentences inferred from content + the stated niche>",
  "voice": ["<descriptor>", "<descriptor>", "<descriptor>"],
  "recurring_themes": ["<theme>", "<theme>", "<theme>"],
  "analyzed_at": "<ISO 8601 timestamp>"
}}

- voice: array of 3-5 short adjectives or phrases.
- recurring_themes: array of 3-5 actual recurring topics.
- niche_source must be exactly "user_provided".
- niche must equal the user's stated niche verbatim.

PROFILE DATA:
{profile_data}

POSTS DATA:
{posts_data}'''

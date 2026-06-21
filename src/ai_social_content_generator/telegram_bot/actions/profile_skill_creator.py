import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.ui import typing_action
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
        await context.bot.send_message(chat_id=update.effective_chat.id,text=f"No cached data for @{handle}, make sure data is cached!")
        return

    profile_data = profile_path.read_text(encoding='utf-8')
    posts_data = posts_path.read_text(encoding='utf-8')

    posts_list = json.loads(posts_data)
    engagement_digest = build_engagement_digest(posts_list, top_n=3)
    logger.info(engagement_digest)

    if niche:
        prompt = build_prompt_with_niche(handle, niche, profile_data, engagement_digest)
    else:
        prompt = build_prompt_with_bio(handle, profile_data, engagement_digest)

    async with typing_action(context.bot, update.effective_chat.id):
        claude_reply = await message_claude(prompt)
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
        await context.bot.send_message(chat_id=update.effective_chat.id,text="No handle found in your account. Please onboard first.")
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
    top_posts = analysis.get("top_posts", [])
    patterns = analysis.get("engagement_patterns", [])

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

    summary = (
        f"📊 Analysis for @{handle}\n\n"
        f"Niche{source_label}:\n{niche}\n\n"
        f"Account Owner:\n{owner}\n\n"
        f"Target Audience:\n{audience}\n\n"
        f"Voice: {voice_str}\n\n"
        f"Recurring Themes:\n{themes_str}"
    )

    if isinstance(top_posts, list) and top_posts:
        post_blocks: list[str] = []
        for post in top_posts:
            if not isinstance(post, dict):
                continue
            post_type = post.get("type", "Post")
            score = post.get("engagement_score", 0)
            why = post.get("why_it_worked", "")
            score_str = f"{score:,}" if isinstance(score, (int, float)) else str(score)
            unit = "views" if post_type == "Video" else "likes"
            block = f"- {post_type} — {score_str} {unit}"
            if why:
                block += f"\n  Why it worked: {why}"
            post_blocks.append(block)
        if post_blocks:
            summary += "\n\n📈 Top-Performing Content:\n\n" + "\n\n".join(post_blocks)

    if patterns:
        if isinstance(patterns, list):
            patterns_str = "\n".join(f"• {p}" for p in patterns)
        else:
            patterns_str = str(patterns)
        summary += f"\n\n🎯 What Works on Your Account:\n{patterns_str}"

    return summary


def build_engagement_digest(posts: list[dict], top_n: int = 3) -> str:
    if not posts:
        return "No posts available."

    def score(post: dict) -> int:
        if post.get("type") == "Video":
            return post.get("videoPlayCount") or post.get("likesCount") or 0
        return post.get("likesCount") or 0

    ranked = sorted(posts, key=score, reverse=True)[:top_n]

    sections: list[str] = []
    for i, post in enumerate(ranked, start=1):
        post_type = post.get("type", "Unknown")
        likes = post.get("likesCount") or 0
        comments = post.get("commentsCount") or 0

        parts = [f"{likes:,} likes", f"{comments:,} comments"]
        if post_type == "Video":
            views = post.get("videoPlayCount")
            if views:
                parts.append(f"{views:,} views")

        header = f"### Post {i} ({post_type}) — " + ", ".join(parts)

        caption = post.get("caption") or ""
        if not caption:
            caption_line = "(no caption)"
        elif len(caption) > 150:
            caption_line = caption[:150] + "..."
        else:
            caption_line = caption

        sections.append(f"{header}\nCaption: {caption_line}")

    return "TOP-PERFORMING POSTS (sorted by engagement):\n\n" + "\n\n".join(sections)


def build_prompt_with_bio(handle: str, profile_data: str, engagement_digest: str) -> str:

    return f'''You are a niche analyzer.

Your task: analyze an Instagram profile to identify niche, audience, voice,
recurring themes, and what drives engagement.

CRITICAL INSTRUCTIONS:
- The bio field is the authoritative source for niche. Trust it.
- Post captions provide evidence of voice and recurring themes ONLY.
- Do NOT redefine the niche based on caption topics.
- If bio and captions seem to contradict, the bio wins.
- Respond in English.
- gender: the grammatical gender of the account OWNER (the person whose
  voice the content speaks in). This drives Hebrew grammar downstream,
  so be careful. Determine it using these signals, in order of reliability:
  1. STRONGEST — if the posts are in Hebrew, look at the gendered
     verb/adjective forms the creator uses about THEMSELVES (e.g.
     "אני עוזר" masculine vs "אני עוזרת" feminine; "מאמן" vs "מאמנת").
     The creator's own self-referential grammar is the most authoritative
     signal — read it off their text rather than guessing.
  2. The bio: gendered job titles or self-descriptions (Hebrew titles are
     gendered: מאמן/מאמנת, יועץ/יועצת, etc.).
  3. The display name / full name.
  Respond with exactly "male" or "female" (lowercase). Prefer signal 1
  when the posts are Hebrew; fall back to 2 and 3 otherwise. Make your
  best determination from the available evidence.

OUTPUT FORMAT:
Return ONLY a single valid JSON object. No markdown fences, no prose
before or after. The object must have exactly these keys:

{{
  "handle": "{handle}",
  "niche": "<1-2 sentences anchored on bio>",
  "niche_source": "inferred_from_bio",
  "account_owner": "<2-3 sentences: credentials and expertise from bio>",
  "gender": "<male | female>",
  "target_audience": "<2-3 sentences inferred from content>",
  "voice": ["<descriptor>", "<descriptor>", "<descriptor>"],
  "recurring_themes": ["<theme>", "<theme>", "<theme>"],
  "top_posts": [
    {{
      "type": "<post type from digest>",
      "engagement_score": <number from digest>,
      "caption_excerpt": "<first 150 chars of caption, with ... if truncated>",
      "why_it_worked": "<1-2 sentences>"
    }}
  ],
  "engagement_patterns": [
    "<pattern observation 1>",
    "<pattern observation 2>",
    "<pattern observation 3>"
  ],
  "analyzed_at": "<ISO 8601 timestamp>"
}}

- voice: array of 3-5 short adjectives or phrases.
- recurring_themes: array of 3-5 topics that come up across posts.
- niche_source must be exactly "inferred_from_bio".

PROFILE DATA:
{profile_data}

ENGAGEMENT ANALYSIS:
The top-performing posts on this account are listed below. Your task
for the engagement section:

For each top post, write a "why_it_worked" reasoning (1-2 sentences).
Look at:
- The caption style (length, tone, hook style)
- The post type (image vs video vs carousel)
- The topic angle (specific event, evergreen advice, story)
- Any concrete elements (dates, numbers, names, products)

Then identify 3-5 engagement_patterns — observations about what
consistently works on this account.

CRITICAL:
- Do NOT invent engagement reasons not supported by the data.
- If only 1-3 posts are available, note "limited data" in patterns.
- Reasoning describes WHY the post worked, not just WHAT it was.
- engagement_score must match the digest exactly.
- top_posts must be ordered the same as the digest.
- caption_excerpt is the first 150 chars from each post's caption,
  truncated with "..." if cut off.
- If the digest below shows "No posts available": top_posts must be []
  and engagement_patterns must be [].

TOP-PERFORMING POSTS:
{engagement_digest}'''


def build_prompt_with_niche(handle: str, niche: str, profile_data: str, engagement_digest: str) -> str:

    return f'''You are analyzing an Instagram account on behalf of its owner.

The account owner has stated their niche as:
"{niche}"

Treat this niche as authoritative ground truth. Do NOT redetermine or
contradict the niche based on bio or caption content. Your job is to
analyze HOW this account expresses this niche through audience, voice,
themes, and what drives engagement.

CRITICAL INSTRUCTIONS:
- niche field: use the user's stated niche above, do NOT infer a different one.
- Even if posts discuss topics that suggest a different specialty, the
  stated niche wins.
- Caption topics are evidence of voice/themes, not niche.
- Respond in English.
- gender: the grammatical gender of the account OWNER (the person whose
  voice the content speaks in). This drives Hebrew grammar downstream,
  so be careful. Determine it using these signals, in order of reliability:
  1. STRONGEST — if the posts are in Hebrew, look at the gendered
     verb/adjective forms the creator uses about THEMSELVES (e.g.
     "אני עוזר" masculine vs "אני עוזרת" feminine; "מאמן" vs "מאמנת").
     The creator's own self-referential grammar is the most authoritative
     signal — read it off their text rather than guessing.
  2. The bio: gendered job titles or self-descriptions (Hebrew titles are
     gendered: מאמן/מאמנת, יועץ/יועצת, etc.).
  3. The display name / full name.
  Respond with exactly "male" or "female" (lowercase). Prefer signal 1
  when the posts are Hebrew; fall back to 2 and 3 otherwise. Make your
  best determination from the available evidence.

OUTPUT FORMAT:
Return ONLY a single valid JSON object. No markdown fences, no prose
before or after. The object must have exactly these keys:

{{
  "handle": "{handle}",
  "niche": "{niche}",
  "niche_source": "user_provided",
  "account_owner": "<2-3 sentences: credentials and expertise from bio>",
  "gender": "<male | female>",
  "target_audience": "<2-3 sentences inferred from content + the stated niche>",
  "voice": ["<descriptor>", "<descriptor>", "<descriptor>"],
  "recurring_themes": ["<theme>", "<theme>", "<theme>"],
  "top_posts": [
    {{
      "type": "<post type from digest>",
      "engagement_score": <number from digest>,
      "caption_excerpt": "<first 150 chars of caption, with ... if truncated>",
      "why_it_worked": "<1-2 sentences>"
    }}
  ],
  "engagement_patterns": [
    "<pattern observation 1>",
    "<pattern observation 2>",
    "<pattern observation 3>"
  ],
  "analyzed_at": "<ISO 8601 timestamp>"
}}

- voice: array of 3-5 short adjectives or phrases.
- recurring_themes: array of 3-5 actual recurring topics.
- niche_source must be exactly "user_provided".
- niche must equal the user's stated niche verbatim.

PROFILE DATA:
{profile_data}

ENGAGEMENT ANALYSIS:
The top-performing posts on this account are listed below. Your task
for the engagement section:

For each top post, write a "why_it_worked" reasoning (1-2 sentences).
Look at:
- The caption style (length, tone, hook style)
- The post type (image vs video vs carousel)
- The topic angle (specific event, evergreen advice, story)
- Any concrete elements (dates, numbers, names, products)

Then identify 3-5 engagement_patterns — observations about what
consistently works on this account.

CRITICAL:
- Do NOT invent engagement reasons not supported by the data.
- If only 1-3 posts are available, note "limited data" in patterns.
- Reasoning describes WHY the post worked, not just WHAT it was.
- engagement_score must match the digest exactly.
- top_posts must be ordered the same as the digest.
- caption_excerpt is the first 150 chars from each post's caption,
  truncated with "..." if cut off.
- If the digest below shows "No posts available": top_posts must be []
  and engagement_patterns must be [].

TOP-PERFORMING POSTS:
{engagement_digest}'''

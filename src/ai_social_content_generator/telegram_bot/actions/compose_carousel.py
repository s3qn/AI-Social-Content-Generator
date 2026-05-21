import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.users import load_user
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.actions.profile_skill_creator import build_engagement_digest

logger = logging.getLogger(__name__)

SKILL_PATH = Path("src/ai_social_content_generator/compose_carousel/SKILL.md")


async def compose_carousel_from_picked(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    topic_core_idea: str,
    chosen_headline: str,
) -> None:
    user_id = update.effective_user.id
    user_data = load_user(user_id)

    if user_data is None or "handle" not in user_data or "niche" not in user_data:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No account info. Please complete onboarding first.",
        )
        return

    handle = user_data["handle"]

    analysis_path = Path(f"cache/{handle}-analysis.json")
    if not analysis_path.exists():
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please run Analyze first before generating ideas.",
        )
        return

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))

    posts_path = Path(f"cache/{handle}-posts.json")
    posts_list = json.loads(posts_path.read_text(encoding="utf-8")) if posts_path.exists() else []
    engagement_digest = build_engagement_digest(posts_list, top_n=3)

    competitors = user_data.get("competitors", [])
    competitor_section = build_competitor_section(competitors)

    skill_template = SKILL_PATH.read_text(encoding="utf-8")

    formatted = _format_analysis_for_prompt(analysis)
    formatted["engagement_digest"] = engagement_digest
    formatted["competitor_section"] = competitor_section
    formatted["chosen_topic"] = topic_core_idea
    formatted["chosen_headline"] = chosen_headline
    prompt = skill_template.format(**formatted)

    claude_reply = await message_claude(prompt)
    raw_output = getattr(claude_reply, "stdout", None)
    returncode = getattr(claude_reply, "returncode", -1)

    if claude_reply is None or returncode != 0 or not raw_output:
        logger.error("Claude failed for handle=%s reply=%r", handle, claude_reply)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Generation failed, try again.",
        )
        return

    marker = "## Attribution"
    idx = raw_output.find(marker)
    if idx != -1:
        carousel_part = raw_output[:idx].rstrip()
        attribution_part = raw_output[idx:].strip()
    else:
        carousel_part = raw_output
        attribution_part = None

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=carousel_part,
    )

    if attribution_part is not None and not is_empty_attribution(attribution_part):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=attribution_part,
        )
        logger.info("Sent carousel + attribution")
    else:
        logger.info("Sent carousel only — no attribution")


def is_empty_attribution(text: str) -> bool:
    body_lines = [
        line for line in text.splitlines()
        if not line.strip().startswith("## Attribution")
    ]
    body = "\n".join(body_lines).strip()

    if not body:
        return True

    body_clean = body.lower().strip(" .,;:!\n\t")
    none_phrases = {
        "none used",
        "no competitors used",
        "no competitors",
        "none",
        "n/a",
        "no",
    }
    if body_clean in none_phrases:
        return True

    has_bullet = any(line.lstrip().startswith(("-", "•", "*")) for line in body.splitlines())
    has_handle = bool(re.search(r"@\w", body))
    if not has_bullet and not has_handle:
        return True

    return False


def _parse_iso_timestamp(ts) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _filter_posts_by_age(posts: list[dict], days: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result: list[dict] = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        ts = _parse_iso_timestamp(post.get("timestamp"))
        if ts is None:
            continue
        if ts >= cutoff:
            result.append(post)
    return result


def _engagement_score(post: dict) -> int:
    if post.get("type") == "Video":
        return max(post.get("videoPlayCount") or 0, post.get("likesCount") or 0, 0)
    return max(post.get("likesCount") or 0, 0)


def _top_n_by_engagement(posts: list[dict], n: int) -> list[dict]:
    return sorted(posts, key=_engagement_score, reverse=True)[:n]


def _caption_excerpt(caption, max_len: int = 150) -> str:
    if not caption or not isinstance(caption, str):
        return ""
    flat = " ".join(caption.split())
    if len(flat) <= max_len:
        return flat
    return flat[:max_len] + "..."


def _format_recent_block(handle: str, posts: list[dict]) -> str:
    lines: list[str] = []
    for post in posts:
        ptype = post.get("type", "Post")
        likes = max(post.get("likesCount") or 0, 0)
        excerpt = _caption_excerpt(post.get("caption"))
        if ptype == "Video":
            views = max(post.get("videoPlayCount") or 0, 0)
            meta = f"{ptype}, {likes:,} likes, {views:,} views"
        else:
            meta = f"{ptype}, {likes:,} likes"
        lines.append(f"- Post ({meta}): {excerpt}")
    return f"### @{handle}\n" + "\n".join(lines)


def _format_analysis_fallback_block(handle: str, top_posts: list[dict]) -> str:
    lines: list[str] = []
    for post in top_posts:
        if not isinstance(post, dict):
            continue
        excerpt = post.get("caption_excerpt", "")
        why = post.get("why_it_worked", "")
        lines.append(f"- Post: {excerpt}\n  Why: {why}")
    if not lines:
        return ""
    return f"### @{handle}\n" + "\n".join(lines)


def _competitor_block(handle: str) -> str:
    posts_path = Path(f"cache/{handle}-posts.json")
    if posts_path.exists():
        try:
            posts = json.loads(posts_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            posts = []
        if isinstance(posts, list):
            recent = _filter_posts_by_age(posts, days=14)
            top = _top_n_by_engagement(recent, n=3)
            if top:
                return _format_recent_block(handle, top)

    analysis_path = Path(f"cache/{handle}-analysis.json")
    if not analysis_path.exists():
        return ""
    try:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""

    top_posts = analysis.get("top_posts", [])
    if not isinstance(top_posts, list):
        return ""

    return _format_analysis_fallback_block(handle, top_posts)


def build_competitor_section(competitor_handles: list[str]) -> str:
    if not competitor_handles:
        return ""

    blocks: list[str] = []
    for handle in competitor_handles:
        block = _competitor_block(handle)
        if block:
            blocks.append(block)

    if not blocks:
        return ""

    body = "\n\n".join(blocks)
    return (
        "COMPETITOR ENGAGEMENT PATTERNS\n\n"
        "Below are top-performing posts from accounts the creator "
        "considers competitors. For each, you'll see what worked and why.\n\n"
        + body
        + "\n\nHow to use this:\n"
        "- Extract the underlying PATTERN behind each successful competitor post.\n"
        "- Apply those patterns to a NEW idea in the creator's niche.\n"
        "- DO NOT use competitor topics. The competitor data informs HOW to "
        "structure the post (the form). The creator's niche informs WHAT "
        "the post is about (the substance).\n"
    )


def _format_analysis_for_prompt(analysis: dict) -> dict:
    handle = analysis.get("handle", "")
    niche = analysis.get("niche", "")
    voice = analysis.get("voice", [])
    themes = analysis.get("recurring_themes", [])
    top_posts = analysis.get("top_posts", [])
    patterns = analysis.get("engagement_patterns", [])

    voice_str = ", ".join(voice) if isinstance(voice, list) else str(voice)

    if isinstance(themes, list):
        themes_str = "\n".join(f"- {t}" for t in themes)
    else:
        themes_str = str(themes)

    if isinstance(patterns, list):
        patterns_str = "\n".join(f"- {p}" for p in patterns)
    else:
        patterns_str = str(patterns)

    if isinstance(top_posts, list):
        post_lines: list[str] = []
        for post in top_posts:
            if not isinstance(post, dict):
                continue
            ptype = post.get("type", "Post")
            excerpt = post.get("caption_excerpt", "")
            why = post.get("why_it_worked", "")
            post_lines.append(f"- {ptype}: {excerpt} (why it worked: {why})")
        top_posts_str = "\n".join(post_lines)
    else:
        top_posts_str = str(top_posts)

    return {
        "handle": handle,
        "niche": niche,
        "voice": voice_str,
        "recurring_themes": themes_str,
        "top_posts": top_posts_str,
        "engagement_patterns": patterns_str,
    }

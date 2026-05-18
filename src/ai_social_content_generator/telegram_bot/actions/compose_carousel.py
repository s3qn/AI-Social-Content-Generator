import json
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import load_user
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.actions.profile_skill_creator import build_engagement_digest

logger = logging.getLogger(__name__)

SKILL_PATH = Path("src/ai_social_content_generator/compose_carousel/SKILL.md")


@require_auth
async def compose_carousel_from_vault(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates a carousel idea from the user's analysis. Called from menu button."""
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

    skill_template = SKILL_PATH.read_text(encoding="utf-8")

    formatted = _format_analysis_for_prompt(analysis)
    formatted["engagement_digest"] = engagement_digest
    prompt = skill_template.format(**formatted)

    claude_reply = message_claude(prompt)
    raw_output = getattr(claude_reply, "stdout", None)
    returncode = getattr(claude_reply, "returncode", -1)

    if claude_reply is None or returncode != 0 or not raw_output:
        logger.error("Claude failed for handle=%s reply=%r", handle, claude_reply)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Generation failed, try again.",
        )
        return

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=raw_output,
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

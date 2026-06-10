import json
import logging
import re
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.users import load_user
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.actions.profile_skill_creator import (
    build_engagement_digest,
)
from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
    build_competitor_section,
    is_empty_attribution,
)

logger = logging.getLogger(__name__)

SKILL_PATH_TALKING_HEAD = Path(
    "src/ai_social_content_generator/compose_reel/SKILL.md"
)
SKILL_PATH_TEXT_OVERLAY = Path(
    "src/ai_social_content_generator/compose_reel_text_overlay/SKILL.md"
)
CONVERT_PATH_TALKING_HEAD = Path(
    "src/ai_social_content_generator/convert_carousel_reel/SKILL.md"
)
CONVERT_PATH_TEXT_OVERLAY = Path(
    "src/ai_social_content_generator/convert_carousel_reel_text_overlay/SKILL.md"
)


def _strip_asterisks(text: str) -> str:
    """*Markers* are carousel render styling, not content — they must not
    reach the conversion prompt."""
    return re.sub(r"\*(.+?)\*", r"\1", text)


async def compose_reel_from_picked(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    topic_core_idea: str,
    chosen_headline: str,
    reel_format: str = "talking_head",
) -> None:
    logger.info("REEL FORMAT: %s", reel_format)
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
    niche = analysis.get("niche") or user_data.get("niche", "")

    voice = analysis.get("voice", [])
    voice_str = ", ".join(voice) if isinstance(voice, list) else str(voice)

    themes = analysis.get("recurring_themes", [])
    if isinstance(themes, list):
        themes_str = "\n".join(f"- {t}" for t in themes)
    else:
        themes_str = str(themes)

    posts_path = Path(f"cache/{handle}-posts.json")
    posts_list = (
        json.loads(posts_path.read_text(encoding="utf-8"))
        if posts_path.exists()
        else []
    )
    engagement_digest = build_engagement_digest(posts_list, top_n=3)

    competitors = user_data.get("competitors", [])
    competitor_section = build_competitor_section(competitors)

    if reel_format == "text_overlay":
        skill_path = SKILL_PATH_TEXT_OVERLAY
    else:
        skill_path = SKILL_PATH_TALKING_HEAD
    skill_template = skill_path.read_text(encoding="utf-8")
    prompt = skill_template.format(
        niche=niche,
        voice_str=voice_str,
        themes_str=themes_str,
        engagement_digest=engagement_digest,
        competitor_section=competitor_section,
        chosen_topic=topic_core_idea,
        chosen_headline=chosen_headline,
    )

    claude_reply = await message_claude(prompt)
    raw_output = getattr(claude_reply, "stdout", None)
    returncode = getattr(claude_reply, "returncode", -1)

    if claude_reply is None or returncode != 0 or not raw_output:
        logger.error("Reel: Claude failed for handle=%s reply=%r", handle, claude_reply)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Reel generation failed, try again.",
        )
        return

    marker = "## Attribution"
    idx = raw_output.find(marker)
    if idx != -1:
        reel_part = raw_output[:idx].rstrip()
        attribution_part = raw_output[idx:].strip()
    else:
        reel_part = raw_output
        attribution_part = None

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=reel_part,
    )

    if attribution_part is not None and not is_empty_attribution(attribution_part):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=attribution_part,
        )
        logger.info("Sent reel + attribution for handle=%s", handle)
    else:
        logger.info("Sent reel only for handle=%s (no attribution)", handle)


async def convert_carousel_to_reel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reel_format: str,
) -> None:
    """One Claude call that re-tells the stashed carousel (including any
    manual slide edits) as a reel in the chosen format. Read-only on
    last_carousel/last_render: the user can still edit/re-render/publish
    the carousel afterward."""
    query = update.callback_query
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    data = context.user_data.get("last_carousel")
    slides = data.get("slides") if data else None
    if not slides:
        await context.bot.send_message(
            chat_id=chat_id, text="Generate a carousel first.",
        )
        return

    user_data = load_user(user_id)
    if user_data is None or "handle" not in user_data or "niche" not in user_data:
        await context.bot.send_message(
            chat_id=chat_id,
            text="No account info. Please complete onboarding first.",
        )
        return

    handle = user_data["handle"]

    analysis_path = Path(f"cache/{handle}-analysis.json")
    if not analysis_path.exists():
        await context.bot.send_message(
            chat_id=chat_id,
            text="Please run Analyze first before generating ideas.",
        )
        return

    format_label = "text overlay" if reel_format == "text_overlay" else "talking head"
    progress = f"🎬 Converting your carousel into a {format_label} reel, ~30-60 sec..."
    if query is not None:
        await query.edit_message_text(progress)
    else:
        await context.bot.send_message(chat_id=chat_id, text=progress)

    hook_slide = next(
        (s for s in slides if s.get("type") == "hook"), slides[0]
    )
    source_hook = _strip_asterisks(hook_slide.get("text", ""))

    slide_lines = []
    for i, slide in enumerate(slides, start=1):
        line = f"{i}. {_strip_asterisks(slide.get('text', ''))}"
        sub = slide.get("sub")
        if sub:
            line += f" ({_strip_asterisks(sub)})"
        slide_lines.append(line)
    source_slides = "\n".join(slide_lines)

    # Caption only — the reel generates its own caption/hashtags per its
    # format rules; the carousel caption is source context, hashtags noise.
    source_caption = data.get("caption", "")

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    niche = analysis.get("niche") or user_data.get("niche", "")

    voice = analysis.get("voice", [])
    voice_str = ", ".join(voice) if isinstance(voice, list) else str(voice)

    themes = analysis.get("recurring_themes", [])
    if isinstance(themes, list):
        themes_str = "\n".join(f"- {t}" for t in themes)
    else:
        themes_str = str(themes)

    posts_path = Path(f"cache/{handle}-posts.json")
    posts_list = (
        json.loads(posts_path.read_text(encoding="utf-8"))
        if posts_path.exists()
        else []
    )
    engagement_digest = build_engagement_digest(posts_list, top_n=3)

    competitors = user_data.get("competitors", [])
    competitor_section = build_competitor_section(competitors)

    if reel_format == "text_overlay":
        skill_path = CONVERT_PATH_TEXT_OVERLAY
    else:
        skill_path = CONVERT_PATH_TALKING_HEAD
    skill_template = skill_path.read_text(encoding="utf-8")
    prompt = skill_template.format(
        niche=niche,
        voice_str=voice_str,
        themes_str=themes_str,
        engagement_digest=engagement_digest,
        competitor_section=competitor_section,
        source_hook=source_hook,
        source_slides=source_slides,
        source_caption=source_caption,
    )

    claude_reply = await message_claude(prompt)
    raw_output = getattr(claude_reply, "stdout", None)
    returncode = getattr(claude_reply, "returncode", -1)

    if claude_reply is None or returncode != 0 or not raw_output:
        logger.error(
            "Convert carousel→reel: Claude failed for handle=%s reply=%r",
            handle, claude_reply,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text="Conversion failed, try again.",
        )
        return

    # DELIBERATELY no vault bookkeeping (no add_headlines_to_topic /
    # mark_headline_used): the carousel already consumed the headline; the
    # reel is a derivative. Marking again would double-count usage.

    marker = "## Attribution"
    idx = raw_output.find(marker)
    if idx != -1:
        reel_part = raw_output[:idx].rstrip()
        attribution_part = raw_output[idx:].strip()
    else:
        reel_part = raw_output
        attribution_part = None

    await context.bot.send_message(chat_id=chat_id, text=reel_part)

    if attribution_part is not None and not is_empty_attribution(attribution_part):
        await context.bot.send_message(chat_id=chat_id, text=attribution_part)
        logger.info("Sent converted reel + attribution for handle=%s", handle)
    else:
        logger.info("Sent converted reel only for handle=%s (no attribution)", handle)

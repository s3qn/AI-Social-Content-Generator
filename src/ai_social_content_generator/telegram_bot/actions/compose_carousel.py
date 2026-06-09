import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import load_user
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.actions.profile_skill_creator import build_engagement_digest
from ai_social_content_generator.instagram.publish import PublishError, publish_carousel
from ai_social_content_generator.instagram.token_store import clear_token, get_token
from ai_social_content_generator.render.carousel_render import render_carousel
from ai_social_content_generator.render.contact_sheet import build_contact_sheet
from ai_social_content_generator.render.mock_post import render_mock_post
from ai_social_content_generator.render.parse_slides import (
    parse_carousel_caption_hashtags,
    parse_carousel_markdown,
)
from ai_social_content_generator.render.publish_staging import (
    StagingError,
    cleanup_staged,
    stage_for_publish,
)

logger = logging.getLogger(__name__)

SKILL_PATH = Path("src/ai_social_content_generator/compose_carousel/SKILL.md")
DEFAULT_BACKGROUND = Path("src/ai_social_content_generator/assets/sample_bg.jpg")
MEDIA_GROUP_MAX = 10  # Telegram cap


def _resolve_background(user_id: int) -> Path:
    """Return the user's uploaded carousel background, falling back to the
    committed default. Phase 3 will add the upload flow; for now any path
    stored in user_data['carousel_background'] wins if it exists on disk."""
    user_data = load_user(user_id)
    bg = user_data.get("carousel_background") if user_data else None
    if bg:
        p = Path(bg)
        if p.exists():
            return p
    return DEFAULT_BACKGROUND


def _resolve_logo(user_id: int) -> Path | None:
    """Return the user's uploaded carousel logo if any, else None. The
    renderer treats None / missing-file as "use the built-in SVG motif"."""
    user_data = load_user(user_id)
    logo = user_data.get("carousel_logo") if user_data else None
    if logo:
        p = Path(logo)
        if p.exists():
            return p
    return None


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

    gen_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎨 Generate images", callback_data="gen_carousel_img")]
    ])
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=carousel_part,
        reply_markup=gen_button,
    )

    # Stash for the later "Generate images" tap. context.user_data persists
    # in-memory across turns within the same chat. A bot restart clears it,
    # which is handled gracefully by generate_carousel_images.
    slides = parse_carousel_markdown(carousel_part)
    caption, hashtags = parse_carousel_caption_hashtags(raw_output)
    context.user_data["last_carousel"] = {
        "slides": slides,
        "handle": handle,
        "caption": caption,
        "hashtags": hashtags,
    }
    logger.info(
        "Stashed last_carousel for user_id=%s: %d slides, caption=%d chars, hashtags=%d chars",
        user_id, len(slides), len(caption), len(hashtags),
    )

    if attribution_part is not None and not is_empty_attribution(attribution_part):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=attribution_part,
        )
        logger.info("Sent carousel + attribution")
    else:
        logger.info("Sent carousel only — no attribution")


@require_auth
async def generate_carousel_images(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the '🎨 Generate images' tap that follows the carousel text.
    Renders slides → contact sheet → sends as photo with follow-up
    individual/publish buttons. Degrades gracefully on render failure —
    the carousel text above stays intact."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    data = context.user_data.get("last_carousel")
    if not data or not data.get("slides"):
        await context.bot.send_message(
            chat_id=chat_id,
            text="Generate a carousel first, then tap Generate images.",
        )
        return

    await context.bot.send_message(
        chat_id=chat_id, text="🎨 Rendering images, about 15 seconds...",
    )

    try:
        bg = _resolve_background(user_id)
        logo = _resolve_logo(user_id)
        out_dir = Path("cache") / "render" / str(user_id)
        paths = await render_carousel(
            data["slides"], data["handle"], bg, out_dir, logo_path=logo,
        )
        sheet = build_contact_sheet(paths, out_dir / "contact_sheet.png")
    except Exception:
        logger.exception("Carousel image render failed for user_id=%s", user_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Image rendering failed. Your carousel text above is unaffected.",
        )
        return

    context.user_data["last_render"] = {
        "paths": [str(p) for p in paths],
        "sheet": str(sheet),
    }

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📥 Get individual posts", callback_data="gen_carousel_individual"
        )],
        [InlineKeyboardButton(
            "📤 Upload to Instagram", callback_data="gen_carousel_publish"
        )],
    ])
    try:
        with open(sheet, "rb") as f:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption="Here's your carousel.",
                reply_markup=kb,
            )
        logger.info(
            "Sent carousel sheet to user_id=%s (%d slides)", user_id, len(paths),
        )
    except Exception:
        logger.exception("Failed to send contact sheet for user_id=%s", user_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Images rendered but failed to send. Try again.",
        )


@require_auth
async def carousel_individual_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Send the rendered slides as an individual-photos album."""
    query = update.callback_query
    chat_id = update.effective_chat.id

    data = context.user_data.get("last_render")
    if not data or not data.get("paths"):
        await query.answer("Generate images first.", show_alert=True)
        return
    await query.answer()

    paths = [Path(p) for p in data["paths"]][:MEDIA_GROUP_MAX]
    missing = [p for p in paths if not p.exists()]
    if missing:
        logger.warning("carousel_individual_route: missing files: %s", missing)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Rendered images are no longer on disk. Tap 🎨 Generate images again.",
        )
        return

    open_files: list = []
    try:
        media = []
        for p in paths:
            fh = open(p, "rb")
            open_files.append(fh)
            media.append(InputMediaPhoto(fh))
        await context.bot.send_media_group(chat_id=chat_id, media=media)
        logger.info("Sent individual posts (%d) to chat_id=%s", len(paths), chat_id)
    except Exception:
        logger.exception("Failed to send media group to chat_id=%s", chat_id)
        await context.bot.send_message(
            chat_id=chat_id, text="Couldn't send the album. Try again.",
        )
    finally:
        for fh in open_files:
            try:
                fh.close()
            except Exception:
                pass


@require_auth
async def carousel_publish_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Phase 1: render a mock IG post (first slide + handle + full caption +
    hashtags) and send Confirm/Cancel buttons. No real publishing yet, and
    no public staging — Phase 3 will own both. Failures degrade gracefully:
    the rendered carousel above stays intact."""
    query = update.callback_query
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    render_data = context.user_data.get("last_render")
    carousel_data = context.user_data.get("last_carousel")
    if not render_data or not render_data.get("paths") or not carousel_data:
        await query.answer("Generate images first.", show_alert=True)
        return
    await query.answer()

    paths = [Path(p) for p in render_data["paths"]]
    first_slide = paths[0] if paths else None
    if first_slide is None or not first_slide.exists():
        await context.bot.send_message(
            chat_id=chat_id,
            text="Rendered images are no longer on disk. Tap 🎨 Generate images again.",
        )
        return

    handle = carousel_data.get("handle", "")
    caption = carousel_data.get("caption", "") or ""
    hashtags = carousel_data.get("hashtags", "") or ""
    slide_count = len(paths)

    mock_dir = Path("cache") / "render" / str(user_id)
    mock_dir.mkdir(parents=True, exist_ok=True)
    mock_path = mock_dir / "mock_post.png"

    try:
        await render_mock_post(
            first_slide_path=first_slide,
            handle=handle,
            caption=caption,
            hashtags=hashtags,
            slide_count=slide_count,
            out_path=mock_path,
        )
    except Exception:
        logger.exception("Mock IG post render failed for user_id=%s", user_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Couldn't render the post preview. Try again.",
        )
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Looks good, publish", callback_data="gen_carousel_confirm"
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data="gen_carousel_cancel")],
    ])
    try:
        with open(mock_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption="Preview of how your post will look. Publish?",
                reply_markup=kb,
            )
        logger.info("Sent mock IG post preview to user_id=%s", user_id)
    except Exception:
        logger.exception("Failed to send mock IG post for user_id=%s", user_id)
        await context.bot.send_message(
            chat_id=chat_id, text="Couldn't send the preview. Try again.",
        )


@require_auth
async def carousel_confirm_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Real publish. Token-gate → stage slides to the public folder →
    run the IG carousel publish flow → message the user with a permalink.
    Cleanup always runs in finally so the public folder doesn't leak
    files on failure."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    tok = get_token(user_id)
    if not tok:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Connect Instagram first in Settings → 📷 Connect Instagram.",
        )
        return
    ig_account_id = tok.get("ig_account_id")
    if not ig_account_id:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Instagram account id missing — reconnect from Settings.",
        )
        return

    render_data = context.user_data.get("last_render")
    carousel_data = context.user_data.get("last_carousel")
    if not render_data or not render_data.get("paths") or not carousel_data:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Generate images first.",
        )
        return

    caption = (carousel_data.get("caption") or "").strip()
    hashtags = (carousel_data.get("hashtags") or "").strip()
    caption_full = f"{caption}\n\n{hashtags}".strip()

    try:
        await query.edit_message_caption(caption="📤 Publishing to Instagram…")
    except Exception:
        # Original message wasn't a photo we own, or was already edited; not fatal.
        pass

    slide_paths = [Path(p) for p in render_data["paths"]]
    staged_paths: list[Path] = []
    try:
        staged = stage_for_publish(slide_paths)
        image_urls = [u for u, _ in staged]
        staged_paths = [p for _, p in staged]
    except StagingError:
        logger.exception("Staging failed for user_id=%s", user_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Couldn't prepare images for upload. Try again.",
        )
        return

    try:
        result = await publish_carousel(
            ig_id=str(ig_account_id),
            image_urls=image_urls,
            caption=caption_full,
            token=tok["token"],
        )
        permalink = result.get("permalink")
        if permalink:
            text = f"✅ Posted to Instagram!\n{permalink}"
        else:
            text = "✅ Posted to Instagram!"
        await context.bot.send_message(chat_id=chat_id, text=text)
        logger.info(
            "IG publish OK user_id=%s media_id=%s",
            user_id, result.get("media_id"),
        )
    except PublishError as e:
        if e.auth_failed:
            clear_token(user_id)
            logger.warning(
                "IG publish auth failed user_id=%s, cleared token: %s", user_id, e,
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Instagram rejected the token. Reconnect from Settings → "
                    "📷 Connect Instagram and try again."
                ),
            )
        else:
            logger.warning("IG publish failed user_id=%s: %s", user_id, e)
            await context.bot.send_message(
                chat_id=chat_id,
                text="Couldn't publish to Instagram. Your images are safe — try again.",
            )
    except Exception:
        logger.exception("Unexpected IG publish error user_id=%s", user_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Something went wrong publishing. Try again.",
        )
    finally:
        cleanup_staged(staged_paths)


@require_auth
async def carousel_cancel_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Phase 1: acknowledge the cancel. There's no staging yet, so nothing
    public to clean up — Phase 3 will add cleanup when staging lands."""
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_caption(caption="Cancelled — nothing was posted.")
    except Exception:
        # Message might not be editable (e.g., not a photo); fall back to a reply.
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Cancelled — nothing was posted.",
        )


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

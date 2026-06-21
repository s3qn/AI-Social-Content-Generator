import json
import logging
import re
import shutil
import time
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
from ai_social_content_generator.telegram_bot.users import load_user, save_user
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
from ai_social_content_generator.telegram_bot.actions.scheduled_posts import (
    SCHEDULE_MAX_DAYS,
    SCHEDULE_TZ,
    SCHEDULED_DIR,
    add_scheduled_post,
    format_ts,
    new_post_id,
    parse_schedule_input,
    schedule_post_job,
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


def _carousel_action_keyboard() -> InlineKeyboardMarkup:
    """Buttons attached to every contact-sheet message — initial generate,
    re-render, and post-edit. One helper so the set can't drift between
    callers (the spec was explicit about this)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Edit text", callback_data="gen_carousel_edit")],
        [InlineKeyboardButton("🎬 Make a reel", callback_data="gen_carousel_makereel")],
        [InlineKeyboardButton(
            "📥 Get individual posts", callback_data="gen_carousel_individual"
        )],
        [InlineKeyboardButton(
            "📤 Upload to Instagram", callback_data="gen_carousel_publish"
        )],
    ])


def _escape_codeblock(s: str) -> str:
    """Escape a string for a MarkdownV2 ``` ``` ``` code block. Inside a
    fenced code block, only backslash and backtick need escaping —
    asterisks and underscores render literally, which is exactly what we
    want so the user can SEE and edit the *highlight* markers."""
    return s.replace("\\", "\\\\").replace("`", "\\`")


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

    # Inject the creator's own instructions AFTER .format() via a sentinel
    # replace: her free text never passes through str.format(), so literal
    # braces (e.g. "use {emoji}") can't raise KeyError. Empty/old vaults
    # resolve to a neutral line, keeping default output unchanged.
    custom = (user_data.get("custom_instructions") or {}).get("carousel", "").strip()
    prompt = prompt.replace(
        "<<<CUSTOM_INSTRUCTIONS>>>",
        custom if custom else "(none provided; use your default judgment)",
    )

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

    try:
        with open(sheet, "rb") as f:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption="Here's your carousel.",
                reply_markup=_carousel_action_keyboard(),
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


async def _rerender_and_send(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    progress_text: str,
    success_caption: str,
) -> None:
    """Shared re-render path: pull slides from last_carousel, resolve bg
    and logo fresh, render, build sheet, overwrite last_render so a
    follow-up publish picks up the new images, and send the sheet with
    the action keyboard. Used by both the Re-render menu action and the
    edit-capture flow.

    Caller is responsible for guarding the no-stash case before calling
    this — by the time we're here, last_carousel must be present and
    have slides."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    data = context.user_data.get("last_carousel")
    if not data or not data.get("slides"):
        # Defensive — callers should have guarded already, but never crash.
        await context.bot.send_message(
            chat_id=chat_id,
            text="No recent carousel to re-render. Generate a carousel first.",
        )
        return

    await context.bot.send_message(chat_id=chat_id, text=progress_text)

    try:
        bg = _resolve_background(user_id)
        logo = _resolve_logo(user_id)
        out_dir = Path("cache") / "render" / str(user_id)
        paths = await render_carousel(
            data["slides"], data["handle"], bg, out_dir, logo_path=logo,
        )
        sheet = build_contact_sheet(paths, out_dir / "contact_sheet.png")
    except Exception:
        logger.exception("Re-render failed for user_id=%s", user_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Re-render failed. Your previous images are unaffected.",
        )
        return

    # CRITICAL: overwrite last_render so a subsequent Upload to Instagram
    # publishes the freshly-rendered images, not the originals.
    context.user_data["last_render"] = {
        "paths": [str(p) for p in paths],
        "sheet": str(sheet),
    }

    try:
        with open(sheet, "rb") as f:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption=success_caption,
                reply_markup=_carousel_action_keyboard(),
            )
        logger.info(
            "Re-rendered carousel for user_id=%s (%d slides)", user_id, len(paths),
        )
    except Exception:
        logger.exception("Failed to send re-rendered sheet for user_id=%s", user_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Re-rendered, but couldn't send the preview. Try again.",
        )


@require_auth
async def rerender_current_carousel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Re-render the session's current carousel with whatever background
    + logo are set NOW, without going back to Claude. Same parsed slides,
    fresh visual styling.

    Session-only: reads from context.user_data["last_carousel"], which is
    in-memory and does not survive a bot restart. The natural use case
    happens right after generating, so this is fine in practice and we
    degrade gracefully when the stash is gone."""
    query = update.callback_query
    await query.answer()

    data = context.user_data.get("last_carousel")
    if not data or not data.get("slides"):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "No recent carousel to re-render. Generate a carousel first, "
                "then change the background or logo and come back here."
            ),
        )
        return

    await _rerender_and_send(
        update, context,
        progress_text="🔄 Re-rendering with your current background/logo…",
        success_caption="Re-rendered with your current styling.",
    )


def _edit_slide_picker(slide_count: int) -> InlineKeyboardMarkup:
    """Slide-picker keyboard for the Edit-text flow. One row per three
    slides keeps the picker compact for 5-9 slides; trailing Cancel."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i in range(1, slide_count + 1):
        row.append(InlineKeyboardButton(f"Slide {i}", callback_data=f"edit_slide_{i}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("➕ Add slide", callback_data="slide_add")])
    rows.append([InlineKeyboardButton("➖ Remove slide", callback_data="slide_remove")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel")])
    return InlineKeyboardMarkup(rows)


@require_auth
async def carousel_edit_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Edit-text tap: show a per-slide picker (Slide 1 / Slide 2 / … +
    Cancel), or a friendly message if there's no current carousel in the
    session stash."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    data = context.user_data.get("last_carousel")
    slides = data.get("slides") if data else None
    if not slides:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Generate a carousel first, then tap Edit text.",
        )
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text="✏️ Pick a slide to edit:",
        reply_markup=_edit_slide_picker(len(slides)),
    )


@require_auth
async def carousel_edit_slide_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """User picked a specific slide to edit. Stash editing_slide so the
    next text message gets captured as the new slide text. Send the
    current raw text in a MarkdownV2 code block (asterisks visible and
    copyable; backslash/backtick are the only chars that need escaping
    inside a fenced code block)."""
    query = update.callback_query
    chat_id = update.effective_chat.id

    try:
        n = int(query.data.removeprefix("edit_slide_"))
    except ValueError:
        await query.answer("Bad slide pick.", show_alert=True)
        return

    data = context.user_data.get("last_carousel")
    slides = data.get("slides") if data else None
    if not slides or n < 1 or n > len(slides):
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id,
            text="Couldn't find that slide. Generate a carousel again.",
        )
        return

    await query.answer()

    context.user_data["editing_slide"] = n
    slide_text = slides[n - 1].get("text", "") or ""

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"✏️ Editing Slide {n}. Here's the current text — tap to copy, "
            "edit it, and send it back.\n\n"
            "Tip: keep or move the *stars* to control which words are "
            "highlighted in the image."
        ),
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"```\n{_escape_codeblock(slide_text)}\n```",
        parse_mode="MarkdownV2",
    )


@require_auth
async def carousel_edit_cancel_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """User backed out of the picker. Clear the flag and acknowledge —
    no edit, no re-render."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("editing_slide", None)
    try:
        await query.edit_message_text("Edit cancelled.")
    except Exception:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Edit cancelled.",
        )


# Floor of 2 so a hook+cta minimum always survives a remove.
SLIDE_MIN_FLOOR = 2
# Teaching placeholder for a freshly-added slide; the *stars* show the
# user how to mark highlighted words. Shown literally in a code block,
# then edited via the existing editing_slide capture.
SLIDE_PLACEHOLDER = "Change this text into *something you want.*"


@require_auth
async def slide_remove_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """➖ Remove slide tap: show a per-slide picker, or block when the
    carousel is already at the 2-slide floor."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    data = context.user_data.get("last_carousel")
    slides = data.get("slides") if data else None
    if not slides:
        await context.bot.send_message(
            chat_id=chat_id, text="Generate a carousel first.",
        )
        return
    if len(slides) <= SLIDE_MIN_FLOOR:
        await context.bot.send_message(
            chat_id=chat_id,
            text="A carousel needs at least 2 slides; can't remove more.",
        )
        return

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i in range(1, len(slides) + 1):
        row.append(InlineKeyboardButton(f"Slide {i}", callback_data=f"slide_rm_{i}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel")])
    await context.bot.send_message(
        chat_id=chat_id,
        text="➖ Pick a slide to remove:",
        reply_markup=InlineKeyboardMarkup(rows),
    )


@require_auth
async def slide_remove_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Remove the picked slide and re-render. Position-derived types
    self-heal the structure; page numbers renumber automatically."""
    query = update.callback_query
    chat_id = update.effective_chat.id

    try:
        n = int(query.data.removeprefix("slide_rm_"))
    except ValueError:
        await query.answer("Bad slide pick.", show_alert=True)
        return

    data = context.user_data.get("last_carousel")
    slides = data.get("slides") if data else None
    if not slides or n < 1 or n > len(slides):
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id,
            text="Couldn't find that slide. Generate a carousel again.",
        )
        return
    # Re-check the floor in the route too (guards a stale double-tap).
    if len(slides) <= SLIDE_MIN_FLOOR:
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id,
            text="A carousel needs at least 2 slides; can't remove more.",
        )
        return

    await query.answer()
    slides.pop(n - 1)
    await _rerender_and_send(
        update, context,
        progress_text="🎨 Re-rendering without that slide…",
        success_caption="Slide removed.",
    )


@require_auth
async def slide_add_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """➕ Add slide tap: show an insertion-point picker. slide_ins_K
    inserts at list index K (0 = prepend, N = append)."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    data = context.user_data.get("last_carousel")
    slides = data.get("slides") if data else None
    if not slides:
        await context.bot.send_message(
            chat_id=chat_id, text="Generate a carousel first.",
        )
        return

    n = len(slides)
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("⏮ At the start", callback_data="slide_ins_0")]
    ]
    row: list[InlineKeyboardButton] = []
    for k in range(1, n):  # "After slide k" == insert at index k
        row.append(InlineKeyboardButton(
            f"After slide {k}", callback_data=f"slide_ins_{k}"
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⏭ At the end", callback_data=f"slide_ins_{n}")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel")])
    await context.bot.send_message(
        chat_id=chat_id,
        text="➕ Where should the new slide go?",
        reply_markup=InlineKeyboardMarkup(rows),
    )


@require_auth
async def slide_add_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Insert a placeholder slide at the chosen index, then drive the
    EXISTING editing_slide capture so the user's next message edits it
    and triggers _rerender_and_send — add+edit is one continuous flow,
    no new capture branch."""
    query = update.callback_query
    chat_id = update.effective_chat.id

    try:
        k = int(query.data.removeprefix("slide_ins_"))
    except ValueError:
        await query.answer("Bad position.", show_alert=True)
        return

    data = context.user_data.get("last_carousel")
    slides = data.get("slides") if data else None
    if not slides:
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id, text="Generate a carousel first.",
        )
        return
    if k < 0 or k > len(slides):
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id,
            text="Couldn't place the slide. Generate a carousel again.",
        )
        return

    await query.answer()
    # type is advisory now; position decides render treatment.
    slides.insert(k, {"type": "body", "n": 0, "text": SLIDE_PLACEHOLDER, "sub": None})
    # The new slide is at 1-based position k+1; the existing capture
    # mutates slides[editing-1] and re-renders.
    context.user_data["editing_slide"] = k + 1

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"✍️ New slide added at position {k + 1}. Here's a starter — "
            "tap to copy, edit it, and send it back. Keep or move the "
            "*stars* to highlight words."
        ),
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"```\n{_escape_codeblock(SLIDE_PLACEHOLDER)}\n```",
        parse_mode="MarkdownV2",
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
    """Upload-to-Instagram tap: offer Post now vs Schedule for later. Both
    paths need a current render in session, so guard here once."""
    query = update.callback_query
    chat_id = update.effective_chat.id

    render_data = context.user_data.get("last_render")
    carousel_data = context.user_data.get("last_carousel")
    if not render_data or not render_data.get("paths") or not carousel_data:
        await query.answer("Generate images first.", show_alert=True)
        return
    await query.answer()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Post now", callback_data="gen_carousel_postnow")],
        [InlineKeyboardButton(
            "📅 Schedule for later", callback_data="gen_carousel_schedule"
        )],
    ])
    await context.bot.send_message(
        chat_id=chat_id,
        text="Post now, or schedule it for later?",
        reply_markup=kb,
    )


@require_auth
async def carousel_postnow_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Render a mock IG post (first slide + handle + full caption +
    hashtags) and send Confirm/Cancel buttons. Failures degrade gracefully:
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


async def _publish_carousel_from_data(
    *,
    user_id: int,
    slide_paths: list[Path],
    caption: str,
    hashtags: str,
    ig_account_id: str,
    token: str,
) -> dict:
    """Stage → publish_carousel → permalink → cleanup. Session-free: takes
    explicit args, reads NO context.user_data. Both the live confirm path
    and the scheduled job call this.

    Returns {"ok": True, "permalink": str|None, "media_id": ...} on success
    or {"ok": False, "error": "staging"|"auth"|"publish"|"unexpected"} on
    failure. On an auth failure the (now-invalid) token is cleared here so
    both callers behave identically; each caller does its own notifying."""
    caption_full = f"{(caption or '').strip()}\n\n{(hashtags or '').strip()}".strip()
    staged_paths: list[Path] = []
    try:
        try:
            staged = stage_for_publish(slide_paths)
            image_urls = [u for u, _ in staged]
            staged_paths = [p for _, p in staged]
        except StagingError:
            logger.exception("Staging failed for user_id=%s", user_id)
            return {"ok": False, "error": "staging"}

        try:
            result = await publish_carousel(
                ig_id=str(ig_account_id),
                image_urls=image_urls,
                caption=caption_full,
                token=token,
            )
            logger.info(
                "IG publish OK user_id=%s media_id=%s",
                user_id, result.get("media_id"),
            )
            return {
                "ok": True,
                "permalink": result.get("permalink"),
                "media_id": result.get("media_id"),
            }
        except PublishError as e:
            if e.auth_failed:
                clear_token(user_id)
                logger.warning(
                    "IG publish auth failed user_id=%s, cleared token: %s",
                    user_id, e,
                )
                return {"ok": False, "error": "auth"}
            logger.warning("IG publish failed user_id=%s: %s", user_id, e)
            return {"ok": False, "error": "publish"}
        except Exception:
            logger.exception("Unexpected IG publish error user_id=%s", user_id)
            return {"ok": False, "error": "unexpected"}
    finally:
        cleanup_staged(staged_paths)


@require_auth
async def carousel_confirm_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Live publish. Token-gate, gather from session, then hand off to the
    session-free publisher and map its result to the same user messages as
    before."""
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

    try:
        await query.edit_message_caption(caption="📤 Publishing to Instagram…")
    except Exception:
        # Original message wasn't a photo we own, or was already edited; not fatal.
        pass

    slide_paths = [Path(p) for p in render_data["paths"]]
    result = await _publish_carousel_from_data(
        user_id=user_id,
        slide_paths=slide_paths,
        caption=carousel_data.get("caption") or "",
        hashtags=carousel_data.get("hashtags") or "",
        ig_account_id=str(ig_account_id),
        token=tok["token"],
    )

    if result.get("ok"):
        permalink = result.get("permalink")
        text = f"✅ Posted to Instagram!\n{permalink}" if permalink else "✅ Posted to Instagram!"
        await context.bot.send_message(chat_id=chat_id, text=text)
        return

    err = result.get("error")
    if err == "staging":
        msg = "Couldn't prepare images for upload. Try again."
    elif err == "auth":
        msg = (
            "Instagram rejected the token. Reconnect from Settings → "
            "📷 Connect Instagram and try again."
        )
    elif err == "publish":
        msg = "Couldn't publish to Instagram. Your images are safe — try again."
    else:
        msg = "Something went wrong publishing. Try again."
    await context.bot.send_message(chat_id=chat_id, text=msg)


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


@require_auth
async def carousel_schedule_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """📅 Schedule for later: snapshot the current render now (session is
    only reliable at THIS step), then ask for a date/time."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    render_data = context.user_data.get("last_render")
    carousel_data = context.user_data.get("last_carousel")
    if not render_data or not render_data.get("paths") or not carousel_data:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Generate a carousel and its images first, then schedule.",
        )
        return

    # Snapshot what we need so a later regenerate can't shift the metadata.
    # The actual image files are copied to a per-post folder at capture time.
    context.user_data["pending_schedule"] = {
        "paths": list(render_data["paths"]),
        "caption": carousel_data.get("caption") or "",
        "hashtags": carousel_data.get("hashtags") or "",
    }
    context.user_data["awaiting_schedule_time"] = True

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "📅 Send the date & time to publish "
            "(format: DD/MM/YYYY HH:MM, Israel time).\n\n"
            "Example: 25/06/2026 09:00"
        ),
    )


async def receive_schedule_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """message_bot branch for awaiting_schedule_time: parse + validate the
    datetime, then persist and schedule. Re-prompts (flag stays set) on a
    bad format or a past/absurd date."""
    text = (update.message.text or "").strip()

    dt = parse_schedule_input(text)
    if dt is None:
        await update.message.reply_text(
            "Couldn't read that. Use DD/MM/YYYY HH:MM (Israel time), "
            "e.g. 25/06/2026 09:00."
        )
        return  # keep the flag set

    now = datetime.now(SCHEDULE_TZ)
    if dt <= now:
        await update.message.reply_text(
            "That time is in the past. Send a future date & time "
            "(DD/MM/YYYY HH:MM)."
        )
        return
    if dt > now + timedelta(days=SCHEDULE_MAX_DAYS):
        await update.message.reply_text(
            f"That's too far ahead. Pick a time within {SCHEDULE_MAX_DAYS} days."
        )
        return

    if not context.user_data.get("pending_schedule"):
        context.user_data.pop("awaiting_schedule_time", None)
        await update.message.reply_text(
            "Lost the carousel to schedule. Generate it again and retry."
        )
        return

    await _persist_and_schedule(update, context, dt)


async def _persist_and_schedule(
    update: Update, context: ContextTypes.DEFAULT_TYPE, when: datetime
) -> None:
    """Copy slides to a permanent per-post folder, write the vault record,
    and register the run_once job. The copy is the whole point: the post
    owns its images and survives the next carousel overwriting cache/render."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    pending = context.user_data.get("pending_schedule") or {}

    # ig_account_id snapshot (the token itself is fetched fresh at fire time).
    tok = get_token(user_id)
    ig_account_id = (tok or {}).get("ig_account_id")
    if not tok or not ig_account_id:
        context.user_data.pop("awaiting_schedule_time", None)
        context.user_data.pop("pending_schedule", None)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Connect Instagram first in Settings → 📷 Connect Instagram, "
                 "then schedule.",
        )
        return

    post_id = new_post_id()
    image_dir = SCHEDULED_DIR / str(user_id) / post_id
    image_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for i, src in enumerate(pending.get("paths", []), start=1):
        src_path = Path(src)
        if not src_path.exists():
            continue
        shutil.copy2(src_path, image_dir / f"slide_{i:02d}.png")
        copied += 1

    if copied == 0:
        shutil.rmtree(image_dir, ignore_errors=True)
        context.user_data.pop("awaiting_schedule_time", None)
        context.user_data.pop("pending_schedule", None)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Couldn't save the images to schedule. Generate the carousel "
                 "again and retry.",
        )
        return

    record = {
        "id": post_id,
        "scheduled_ts": int(when.timestamp()),
        "image_dir": str(image_dir),
        "caption": pending.get("caption", ""),
        "hashtags": pending.get("hashtags", ""),
        "ig_account_id": str(ig_account_id),
        "status": "pending",
        "created_ts": int(time.time()),
    }

    user_data = load_user(user_id)
    if user_data is None:
        shutil.rmtree(image_dir, ignore_errors=True)
        context.user_data.pop("awaiting_schedule_time", None)
        context.user_data.pop("pending_schedule", None)
        await context.bot.send_message(
            chat_id=chat_id, text="No account info. Please complete onboarding first.",
        )
        return

    add_scheduled_post(user_data, record)
    save_user(user_id, user_data)
    schedule_post_job(context.application, user_id, record)

    context.user_data.pop("awaiting_schedule_time", None)
    context.user_data.pop("pending_schedule", None)

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📅 Scheduled for {format_ts(record['scheduled_ts'])} (Israel).\n"
            "View or cancel it from 📅 Scheduled posts in the menu."
        ),
    )


@require_auth
async def carousel_makereel_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Make-a-reel tap on the contact-sheet message: show the reel format
    picker. Sent as a NEW message — the button lives on a photo message,
    which can't edit_message_text into a picker."""
    query = update.callback_query
    await query.answer()

    data = context.user_data.get("last_carousel")
    if not data or not data.get("slides"):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Generate a carousel first.",
        )
        return

    from ai_social_content_generator.reel_formats import get_reel_formats
    # Convert-from-carousel needs a convert template; custom formats are
    # compose-only (no convert_template_path), so filter them out here.
    formats = [
        f for f in get_reel_formats(update.effective_user.id)
        if f.get("convert_template_path")
    ]
    keyboard = [
        [InlineKeyboardButton(
            f"{fmt['emoji']} {fmt['name']}",
            callback_data=f"convert_reel_{fmt['id']}",
        )]
        for fmt in formats
    ]
    body = "\n\n".join(
        f"{fmt['emoji']} {fmt['name']}: {fmt['description']}" for fmt in formats
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"How do you want this reel to look?\n\n{body}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def carousel_makereel_format_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    # Local imports — compose_reel imports from this module at top level,
    # so importing it back at module top would be circular.
    from ai_social_content_generator.reel_formats import get_reel_format
    from ai_social_content_generator.telegram_bot.actions.compose_reel import (
        convert_carousel_to_reel,
    )

    format_id = query.data.removeprefix("convert_reel_")
    if get_reel_format(update.effective_user.id, format_id) is None:
        logger.error("carousel_makereel_format_route: unknown format id=%r", format_id)
        return
    await convert_carousel_to_reel(update, context, format_id)


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
    # Lowercase so 'Male' / 'Female' / 'MALE' from older or stricter models
    # all normalize to the values the SKILL rule expects. Empty string when
    # the field is missing (analyses from before the gender field landed) —
    # the SKILL rule has an explicit empty-string fallback for that case.
    gender = str(analysis.get("gender") or "").strip().lower()

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
        "gender": gender,
        "recurring_themes": themes_str,
        "top_posts": top_posts_str,
        "engagement_patterns": patterns_str,
    }

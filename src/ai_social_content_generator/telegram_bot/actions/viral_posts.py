import asyncio
import json
import logging
import re
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import (
    MAX_VIRAL_KEYWORDS,
    add_topic,
    add_viral_keyword,
    load_user,
    remove_viral_keyword,
    save_user,
)
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.ingestion.instagram_scraper import (
    build_viral_excel,
    invalidate_viral_cache,
    scrape_and_process_viral_keywords,
    update_cached_transcript,
    viral_excel_path,
)
from ai_social_content_generator.ingestion.transcribe import (
    transcribe_local_segments,
    transcript_text,
    transcript_segments,
)
from ai_social_content_generator.ingestion.frames import extract_frames

logger = logging.getLogger(__name__)

HOOKS_SKILL_PATH = Path("src/ai_social_content_generator/viral_hooks/SKILL.md")
CREATE_FROM_REEL_SKILL_PATH = Path(
    "src/ai_social_content_generator/create_reel_format_from_reel/SKILL.md"
)
VIRAL_FRAMES_DIR = Path("cache/viral_frames")
PACING_HOLD_THRESHOLD = 1.5  # seconds; a gap this long reads as a deliberate hold

# Vault topics are 3-200 chars (same floor/cap as the own-idea flow).
VIRAL_TOPIC_MIN_LEN = 3
VIRAL_TOPIC_MAX_LEN = 200
CARD_CAPTION_EXCERPT = 150

TIER_LABELS = {"biggest": "🏆 Biggest", "resonant": "💬 Resonant"}


def _fmt_views(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _digest_line(rank: int, r: dict) -> str:
    """One-liner for the per-keyword digest: rank, tier emoji, headline
    metric (views for biggest, engagement for resonant), author, lang."""
    tier_emoji = "🏆" if r.get("tier") == "biggest" else "💬"
    if r.get("tier") == "resonant":
        metric = f"{(r.get('engagement_score') or 0) * 100:.1f}% eng"
    else:
        metric = f"{_fmt_views(r.get('likes') or 0)} ❤"
    username = (r.get("username") or "unknown")[:25]
    parts = [
        f"{rank}. {tier_emoji} {_fmt_views(r.get('views') or 0)} views",
        metric,
        f"@{username}",
    ]
    if r.get("lang"):
        parts.append(r["lang"])
    return " · ".join(parts)


def _format_viral_card(r: dict) -> str:
    """Full card text for one reel: tier, stats, language (display-only
    context — ranking is purely by the tier metrics), author, excerpt,
    link. Stays well under Telegram's 1024-char photo-caption cap."""
    tier = TIER_LABELS.get(r.get("tier", ""), r.get("tier", ""))
    parts = [
        tier,
        f"{_fmt_views(r.get('views') or 0)} views",
        f"{(r.get('comments') or 0):,} comments",
    ]
    if r.get("lang"):
        parts.append(r["lang"])
    excerpt = (r.get("caption") or "").strip().replace("\n", " ")
    if len(excerpt) > CARD_CAPTION_EXCERPT:
        excerpt = excerpt[:CARD_CAPTION_EXCERPT] + "..."
    lines = [
        " | ".join(parts),
        f"@{r.get('username', 'unknown')} · {r.get('post_date', 'unknown')}",
    ]
    if excerpt:
        lines.append(f'"{excerpt}"')
    if r.get("post_url"):
        lines.append(r["post_url"])
    if not r.get("local_video"):
        lines.append("🎵 No speech audio (music reel) — no transcript/hooks.")
    return "\n".join(lines)


@require_auth
async def viral_submenu_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_id = update.effective_user.id
    user_data = load_user(user_id)
    keywords = user_data.get("viral_keywords", []) if user_data else []

    header = (
        f"🔥 Viral Posts Research\n\n"
        f"Keywords ({len(keywords)}/{MAX_VIRAL_KEYWORDS}):\n"
    )
    if not keywords:
        body = "No keywords yet. Add some to start researching."
    else:
        body = "\n".join(f"{i + 1}. {kw['text']}" for i, kw in enumerate(keywords))
    text = header + body

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("➕ Add keyword", callback_data="viral_add")],
    ]
    if keywords:
        keyboard.append(
            [InlineKeyboardButton("🗑️ Remove keyword", callback_data="viral_remove")]
        )
        keyboard.append(
            [InlineKeyboardButton("📊 Generate report", callback_data="viral_generate")]
        )
        keyboard.append(
            [InlineKeyboardButton(
                "🔄 Refresh data (clear cache)", callback_data="viral_refresh"
            )]
        )
    keyboard.append([InlineKeyboardButton("← Back", callback_data="viral_back")])

    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query is not None:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=markup,
        )


@require_auth
async def viral_submenu_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "viral_add":
        context.user_data["awaiting_viral_keyword"] = True
        await query.edit_message_text(
            "Send the keyword you want to research (Hebrew or English).\n\n"
            "Examples: 'זוגיות עסקית', 'couples in business', 'marriage and money'"
        )
    elif query.data == "viral_remove":
        await viral_remove_show(update, context)
    elif query.data == "viral_generate":
        await viral_generate_report(update, context)
    elif query.data == "viral_refresh":
        await viral_refresh_cache(update, context)
    elif query.data == "viral_back":
        from ai_social_content_generator.telegram_bot.actions.menu import (
            _main_menu_keyboard,
        )
        await query.edit_message_text(
            "What would you like to do?",
            reply_markup=_main_menu_keyboard(),
        )


async def viral_receive_keyword(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Called from message_bot when awaiting_viral_keyword is True."""
    keyword = update.message.text.strip()
    user_id = update.effective_user.id
    user_data = load_user(user_id)

    if user_data is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No account info. Please complete onboarding first.",
        )
        context.user_data.pop("awaiting_viral_keyword", None)
        return

    result = add_viral_keyword(user_data, keyword)
    if result is None:
        existing_count = len(user_data.get("viral_keywords", []))
        if existing_count >= MAX_VIRAL_KEYWORDS:
            msg = (
                f"Cap reached ({MAX_VIRAL_KEYWORDS} keywords max). "
                f"Remove one first."
            )
        else:
            msg = "Duplicate or empty keyword. Try a different one."
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=msg
        )
    else:
        save_user(user_id, user_data)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Added: {result['text']}",
        )

    context.user_data.pop("awaiting_viral_keyword", None)
    await viral_submenu_show(update, context)


@require_auth
async def viral_remove_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    user_data = load_user(user_id)
    keywords = user_data.get("viral_keywords", []) if user_data else []

    if not keywords:
        keyboard = [[InlineKeyboardButton("← Back", callback_data="viral_back_submenu")]]
        await query.edit_message_text(
            "No keywords to remove.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    lines = [f"{i + 1}. {kw['text']}" for i, kw in enumerate(keywords)]
    text = "Tap a number to remove:\n\n" + "\n".join(lines)

    buttons = [
        InlineKeyboardButton(
            str(i + 1), callback_data=f"viral_remove_pick_{kw['id']}"
        )
        for i, kw in enumerate(keywords)
    ]
    keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    keyboard.append([InlineKeyboardButton("← Back", callback_data="viral_back_submenu")])

    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


@require_auth
async def viral_remove_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    keyword_id = query.data.removeprefix("viral_remove_pick_")
    user_data = load_user(user_id)
    if user_data is None:
        await query.edit_message_text("No account info found.")
        return

    keywords = user_data.get("viral_keywords", [])
    removed_text: str | None = None
    for kw in keywords:
        if kw.get("id") == keyword_id:
            removed_text = kw.get("text")
            break

    removed = remove_viral_keyword(user_data, keyword_id)
    if removed:
        save_user(user_id, user_data)
        if removed_text:
            invalidate_viral_cache(removed_text)
        logger.info("Removed viral keyword id=%s text=%r", keyword_id, removed_text)

    await viral_submenu_show(update, context)


@require_auth
async def viral_back_submenu_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    await viral_submenu_show(update, context)


async def viral_refresh_cache(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    count = invalidate_viral_cache(None)
    plural = "s" if count != 1 else ""
    await query.edit_message_text(
        f"🔄 Cleared cache for {count} keyword{plural}. "
        f"Next 'Generate report' will scrape fresh."
    )
    await asyncio.sleep(1.5)
    await viral_submenu_show(update, context)


async def viral_generate_report(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Runs the pipeline, then sends in-chat import cards per top reel.
    Excel is no longer the primary output — it's built on demand via the
    Get Excel button."""
    query = update.callback_query
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user_data = load_user(user_id)
    keywords = user_data.get("viral_keywords", []) if user_data else []

    if not keywords:
        await query.edit_message_text("No keywords yet. Add some first.")
        return

    kw_texts = [kw["text"] for kw in keywords]
    plural = "s" if len(kw_texts) != 1 else ""
    await query.edit_message_text(
        f"🔍 Scraping {len(kw_texts)} keyword{plural}...\n"
        f"This takes ~2 min per keyword if not cached.\n"
        f"Cached results return instantly."
    )

    try:
        results = await asyncio.to_thread(
            scrape_and_process_viral_keywords, kw_texts, False
        )
    except Exception:
        logger.exception("Viral pipeline failed for keywords=%r", kw_texts)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Scraping failed. Try again or check logs.",
        )
        return

    if not results:
        await context.bot.send_message(
            chat_id=chat_id,
            text="No viral posts found. Try different keywords.",
        )
        return

    # Session-only stash; the digest/card buttons index into it.
    context.user_data["viral_results"] = results

    # ONE compact digest message per keyword (not one photo per post —
    # that was ~15 messages of chat spam). Numbers drill into full cards,
    # same pattern as the topic/headline pickers.
    grouped: dict[str, list[tuple[int, dict]]] = {}
    for idx, r in enumerate(results):
        grouped.setdefault(r.get("keyword_source", "unknown"), []).append((idx, r))

    for kw, entries in grouped.items():
        lines = [f"🔥 {kw}"]
        buttons = []
        for rank, (idx, r) in enumerate(entries, start=1):
            lines.append(_digest_line(rank, r))
            buttons.append(
                InlineKeyboardButton(str(rank), callback_data=f"viral_view_{idx}")
            )
        text = "\n".join(lines)
        if len(text) > 4000:  # Telegram cap 4096; defensive
            text = text[:4000] + "..."
        keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    summary_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Get Excel", callback_data="viral_excel")],
        [InlineKeyboardButton("← Back", callback_data="viral_back")],
    ])
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ {len(results)} posts across {len(kw_texts)} keyword{plural}.\n"
            f"Tap a number for the full post, transcript, and hook ideas."
        ),
        reply_markup=summary_markup,
    )
    logger.info(
        "Sent viral digest for user_id=%s with %d results", user_id, len(results),
    )


@require_auth
async def viral_excel_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Builds and sends the Excel workbook on demand from the stashed
    results."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    results = context.user_data.get("viral_results")
    if not results:
        await context.bot.send_message(
            chat_id=chat_id, text="Report expired — generate again.",
        )
        return

    output_path = viral_excel_path(user_id)
    try:
        await asyncio.to_thread(build_viral_excel, results, output_path)
    except Exception:
        logger.exception("Viral Excel build failed for user_id=%s", user_id)
        await context.bot.send_message(
            chat_id=chat_id, text="Failed to build Excel file. Try again.",
        )
        return

    try:
        with open(output_path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename="viral_report.xlsx",
                caption=(
                    f"📊 {len(results)} posts\n"
                    f"🏆 Biggest (raw views) + 💬 Resonant (engagement ratio)"
                ),
            )
        logger.info(
            "Sent viral Excel for user_id=%s with %d results",
            user_id, len(results),
        )
    except Exception:
        logger.exception("Telegram document send failed for user_id=%s", user_id)
        await context.bot.send_message(
            chat_id=chat_id, text="Excel built but failed to send. Try again.",
        )


async def _show_import_prompt(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str
) -> None:
    """Edit-before-save entry, shared by caption imports and hook
    imports: stash the candidate TEXT in pending_viral_import, show it
    in a copyable block, and offer Keep as-is when it fits the topic
    limits. The normal_message branch + _store_viral_topic do the rest."""
    context.user_data["pending_viral_import"] = {"text": text}

    if text:
        # Local import — _escape_codeblock lives in compose_carousel, which
        # pulls heavy modules; only needed here.
        from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
            _escape_codeblock,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"```\n{_escape_codeblock(text)}\n```",
            parse_mode="MarkdownV2",
        )

    if VIRAL_TOPIC_MIN_LEN <= len(text) <= VIRAL_TOPIC_MAX_LEN:
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("💾 Keep as-is", callback_data="viral_keep_asis")
        ]])
        prompt = "Send the topic as you want it stored, or keep this text as-is:"
    else:
        # Hashtag-soup captions >200 chars (or empty) can't go in the
        # vault verbatim — require an edited version for a clean vault.
        markup = None
        prompt = (
            f"This text is {len(text)} characters "
            f"(topics are {VIRAL_TOPIC_MIN_LEN}-{VIRAL_TOPIC_MAX_LEN}). "
            f"Send the topic as you want it stored:"
        )
    await context.bot.send_message(chat_id=chat_id, text=prompt, reply_markup=markup)


@require_auth
async def viral_add_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """➕ Add as topic: the post's caption goes through edit-before-save."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    try:
        idx = int(query.data.removeprefix("viral_add_"))
    except ValueError:
        logger.error("viral_add_route: bad callback_data=%r", query.data)
        return

    results = context.user_data.get("viral_results")
    if not results or idx < 0 or idx >= len(results):
        await context.bot.send_message(
            chat_id=chat_id, text="Report expired — generate again.",
        )
        return

    r = results[idx]

    # Whisper-evidence rider: original_sounds ≈ talking-head, licensed
    # music ≈ overlay. Gathers data for the parked video-analysis decision.
    logger.info(
        "viral import: tier=%s lang=%s audio_type=%s url=%s",
        r.get("tier"), r.get("lang"), r.get("audio_type"), r.get("post_url"),
    )

    await _show_import_prompt(context, chat_id, (r.get("caption") or "").strip())


@require_auth
async def viral_keep_asis_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    pending = context.user_data.get("pending_viral_import")
    text = (pending or {}).get("text", "") if isinstance(pending, dict) else ""
    if not text:
        context.user_data.pop("pending_viral_import", None)
        await context.bot.send_message(
            chat_id=chat_id, text="Nothing pending — tap ➕ Add as topic again.",
        )
        return

    if not (VIRAL_TOPIC_MIN_LEN <= len(text) <= VIRAL_TOPIC_MAX_LEN):
        # Defensive: the Keep button is hidden in this case, but a stale
        # button from an earlier report could still land here.
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"This text doesn't fit the topic limits "
                f"({VIRAL_TOPIC_MIN_LEN}-{VIRAL_TOPIC_MAX_LEN} characters). "
                f"Send an edited version:"
            ),
        )
        return

    await _store_viral_topic(update, context, text)


async def _store_viral_topic(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    """Shared tail for Keep-as-is (callback) and the edited-text capture
    (plain message) — no callback_query assumed, same duality as
    _use_headline."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    user_data = load_user(user_id)
    if user_data is None:
        context.user_data.pop("pending_viral_import", None)
        await context.bot.send_message(
            chat_id=chat_id,
            text="No account info. Please complete onboarding first.",
        )
        return

    add_topic(user_data, text)
    save_user(user_id, user_data)
    context.user_data.pop("pending_viral_import", None)

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"💾 Added to your topics: '{text}'\n"
            f"It's available in the Carousel/Reel pickers."
        ),
    )


@require_auth
async def viral_view_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Digest number tap → full card for one post, with the local
    thumbnail (CDN URLs are dead by now) and the action buttons."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    try:
        idx = int(query.data.removeprefix("viral_view_"))
    except ValueError:
        logger.error("viral_view_route: bad callback_data=%r", query.data)
        return

    results = context.user_data.get("viral_results")
    if not results or idx < 0 or idx >= len(results):
        await context.bot.send_message(
            chat_id=chat_id, text="Report expired — generate again.",
        )
        return

    r = results[idx]
    card = _format_viral_card(r)

    keyboard = [[InlineKeyboardButton("➕ Add as topic", callback_data=f"viral_add_{idx}")]]
    if r.get("local_video"):
        keyboard.append([InlineKeyboardButton(
            "💡 Generate topics with AI", callback_data=f"viral_hooks_{idx}"
        )])
        keyboard.append([InlineKeyboardButton(
            "🎤 Full transcript", callback_data=f"viral_transcript_{idx}"
        )])
        keyboard.append([InlineKeyboardButton(
            "🧬 Build format from this", callback_data=f"viral_format_{idx}"
        )])
    markup = InlineKeyboardMarkup(keyboard)

    sent = False
    local_thumb = r.get("local_thumb")
    if local_thumb and Path(local_thumb).exists():
        try:
            with open(local_thumb, "rb") as f:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=f, caption=card, reply_markup=markup,
                )
            sent = True
        except Exception:
            logger.warning(
                "viral_view: local thumb send failed (idx=%d path=%s), text fallback",
                idx, local_thumb,
            )
    if not sent:
        await context.bot.send_message(
            chat_id=chat_id, text=card, reply_markup=markup,
        )


async def _ensure_transcript(
    update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int
) -> str | None:
    """Lazy-transcription gate. Returns the transcript ("" when
    impossible: no local video, or Whisper failed), or None when a
    transcription of this post is already in flight (user notified).
    First successful run is written back to BOTH the stash and the
    on-disk viral JSON so it never reruns."""
    chat_id = update.effective_chat.id
    r = context.user_data["viral_results"][idx]

    # Return the TEXT view regardless of stored shape (old reports store a
    # plain string; new ones store {"text","segments"}). 🎤/💡 stay
    # string-only; Phase 3 reads r["transcript"] raw for segments.
    if r.get("transcript"):
        return transcript_text(r["transcript"])

    local_video = r.get("local_video")
    if not local_video or not Path(local_video).exists():
        return ""

    # Double-tap guard: a second 💡/🎤 during the ~22s run must not start
    # a concurrent transcription of the same file.
    in_flight: set = context.user_data.setdefault("viral_transcribing", set())
    pk = r.get("pk") or str(idx)
    if pk in in_flight:
        await context.bot.send_message(
            chat_id=chat_id, text="🎤 Already transcribing this reel — hold on...",
        )
        return None

    in_flight.add(pk)
    try:
        await context.bot.send_message(
            chat_id=chat_id, text="🎤 Transcribing, ~30 sec...",
        )
        # MUST be to_thread: this runs in a callback handler; ~22s of
        # Whisper CPU on the event loop would freeze the bot for everyone.
        result = await asyncio.to_thread(
            transcribe_local_segments, Path(local_video)
        )
    finally:
        in_flight.discard(pk)

    text = result["text"]
    if text:
        # Store the full {"text","segments"} object so Phase 3 pacing can
        # read segments; the cache + future reports reuse it.
        r["transcript"] = result
        await asyncio.to_thread(
            update_cached_transcript, r.get("keyword_source", ""), pk, result,
        )
    return text


@require_auth
async def viral_transcript_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    try:
        idx = int(query.data.removeprefix("viral_transcript_"))
    except ValueError:
        logger.error("viral_transcript_route: bad callback_data=%r", query.data)
        return

    results = context.user_data.get("viral_results")
    if not results or idx < 0 or idx >= len(results):
        await context.bot.send_message(
            chat_id=chat_id, text="Report expired — generate again.",
        )
        return

    transcript = await _ensure_transcript(update, context, idx)
    if transcript is None:
        return
    if not transcript:
        await context.bot.send_message(
            chat_id=chat_id, text="No transcript available for this reel.",
        )
        return

    from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
        _escape_codeblock,
    )
    for i in range(0, len(transcript), 3500):
        chunk = transcript[i:i + 3500]
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"```\n{_escape_codeblock(chunk)}\n```",
            parse_mode="MarkdownV2",
        )


def _fmt_ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def _build_pacing_summary(text: str, segments: list[dict], duration: float) -> str:
    """Human-readable pacing line: duration, word count, words/sec, and any
    detected holds (gaps >= PACING_HOLD_THRESHOLD between segments). Old
    reports have no segments → falls back to a duration-only note."""
    words = len(text.split()) if text else 0
    parts = []
    if duration:
        parts.append(f"Duration ~{duration:.1f}s")
    parts.append(f"{words} words")
    if duration and words:
        parts.append(f"{words / duration:.1f} words/sec")
    summary = ", ".join(parts) + "."

    holds = []
    for a, b in zip(segments, segments[1:]):
        gap = b["start"] - a["end"]
        if gap >= PACING_HOLD_THRESHOLD:
            holds.append(f"{gap:.1f}s pause at ~{_fmt_ts(a['end'])}")
    if holds:
        summary += " Holds: " + "; ".join(holds) + "."
    elif not segments:
        summary += " (No segment timing available; pacing estimated from length.)"
    return summary


@require_auth
async def viral_format_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """🧬: analyze a viral reel (transcript + pacing + frames) into a
    reusable custom reel format. Second front door to the Phase 2 engine."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    try:
        idx = int(query.data.removeprefix("viral_format_"))
    except ValueError:
        logger.error("viral_format_route: bad callback_data=%r", query.data)
        return

    results = context.user_data.get("viral_results")
    if not results or idx < 0 or idx >= len(results):
        await context.bot.send_message(
            chat_id=chat_id, text="Report expired — generate again.",
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
    if not Path(f"cache/{handle}-analysis.json").exists():
        await context.bot.send_message(
            chat_id=chat_id, text="Please run Analyze first before building a format.",
        )
        return

    r = results[idx]
    transcript = await _ensure_transcript(update, context, idx)
    if transcript is None:
        return  # transcription in flight; user already notified

    segments = transcript_segments(r.get("transcript"))
    duration = float(r.get("video_duration") or 0)

    # Extract frames (blocking ffmpeg → to_thread). The button only shows
    # when local_video exists, but guard anyway.
    frames: list[Path] = []
    local_video = r.get("local_video")
    pk = r.get("pk") or str(idx)
    frames_dir = VIRAL_FRAMES_DIR / pk
    if local_video and Path(local_video).exists():
        frames = await asyncio.to_thread(
            extract_frames, Path(local_video), frames_dir, 6,
            duration if duration else None,
        )

    # Thin-input pre-check: nothing to analyze at all.
    if not transcript and not frames:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Couldn't analyze this reel (no speech, no readable frames).",
        )
        return

    pacing = _build_pacing_summary(transcript, segments, duration)
    if frames:
        listing = "\n".join(f"- {f.resolve()}" for f in frames)
        visual_note = (
            "Frames extracted from the reel are attached as image files. "
            "Read and analyze each one:\n" + listing
        )
        image_dir = str(frames_dir.resolve())
    else:
        visual_note = (
            "No usable video frames were available; analyze from the "
            "transcript and pacing only."
        )
        image_dir = ""

    skill = CREATE_FROM_REEL_SKILL_PATH.read_text(encoding="utf-8")
    prompt = skill.format(
        reel_transcript=transcript or "(no speech detected)",
        reel_pacing=pacing,
        reel_visual_note=visual_note,
    )

    username = r.get("username") or "creator"
    auto_name = f"{username}'s format"[:40]

    context.user_data["pending_format"] = {
        "name": auto_name,
        "origin": "reel",
        "reel_prompt": prompt,
        "frames_dir": image_dir,
        "source_reel_pk": pk,
    }
    # Lazy import — reel_formats_ui pulls compose modules; only needed here.
    from ai_social_content_generator.telegram_bot.actions.reel_formats_ui import (
        run_format_preview,
    )
    await run_format_preview(
        update, context,
        progress="🧬 Analyzing this reel into a format, ~30-60 sec...",
    )


@require_auth
async def viral_hooks_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """💡: transcript (+ caption + niche/voice) → one Claude call →
    3-5 hooks adapted to the creator, each addable to the vault."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    try:
        idx = int(query.data.removeprefix("viral_hooks_"))
    except ValueError:
        logger.error("viral_hooks_route: bad callback_data=%r", query.data)
        return

    results = context.user_data.get("viral_results")
    if not results or idx < 0 or idx >= len(results):
        await context.bot.send_message(
            chat_id=chat_id, text="Report expired — generate again.",
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
            text="Please run Analyze first before generating hooks.",
        )
        return

    r = results[idx]
    transcript = await _ensure_transcript(update, context, idx)
    if transcript is None:
        return
    # Empty transcript is fine — the SKILL falls back to caption alone.

    await context.bot.send_message(
        chat_id=chat_id, text="💡 Generating hooks, ~30-60 sec...",
    )

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    niche = analysis.get("niche") or user_data.get("niche", "")
    voice = analysis.get("voice", [])
    voice_str = ", ".join(voice) if isinstance(voice, list) else str(voice)

    skill_template = HOOKS_SKILL_PATH.read_text(encoding="utf-8")
    prompt = skill_template.format(
        transcript=transcript,
        caption=(r.get("caption") or "").strip()[:1000],
        niche=niche,
        voice_str=voice_str,
    )

    claude_reply = await message_claude(prompt)
    raw_output = getattr(claude_reply, "stdout", "") or ""
    returncode = getattr(claude_reply, "returncode", -1)

    if claude_reply is None or returncode != 0 or not raw_output:
        logger.error(
            "Viral hooks: Claude failed for idx=%d reply=%r", idx, claude_reply,
        )
        await context.bot.send_message(
            chat_id=chat_id, text="Couldn't generate topics, try again.",
        )
        return

    parsed = re.findall(r"^\s*\d+\.\s*(.+?)\s*$", raw_output, re.MULTILINE)
    hooks = [h.strip() for h in parsed if h.strip()]
    if not hooks:
        logger.error("Viral hooks: parsed none for idx=%d raw=%r", idx, raw_output)
        await context.bot.send_message(
            chat_id=chat_id, text="Couldn't generate topics, try again.",
        )
        return

    context.user_data["viral_hooks"] = {"idx": idx, "hooks": hooks}

    lines = [f"{n + 1}. {h}" for n, h in enumerate(hooks)]
    buttons = [
        InlineKeyboardButton(str(n + 1), callback_data=f"viral_hookadd_{idx}_{n}")
        for n in range(len(hooks))
    ]
    keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    await context.bot.send_message(
        chat_id=chat_id,
        text="💡 Hooks from this reel (tap a number to add as topic):\n\n"
             + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def viral_hookadd_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Hook number tap → the existing edit-before-save flow, with the
    hook text as the candidate."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    m = re.match(r"^viral_hookadd_(\d+)_(\d+)$", query.data)
    if not m:
        logger.error("viral_hookadd_route: bad callback_data=%r", query.data)
        return
    idx, n = int(m.group(1)), int(m.group(2))

    stash = context.user_data.get("viral_hooks")
    if (
        not stash
        or stash.get("idx") != idx
        or n < 0
        or n >= len(stash.get("hooks", []))
    ):
        await context.bot.send_message(
            chat_id=chat_id, text="Hooks expired — tap 💡 Generate hooks again.",
        )
        return

    await _show_import_prompt(context, chat_id, stash["hooks"][n])

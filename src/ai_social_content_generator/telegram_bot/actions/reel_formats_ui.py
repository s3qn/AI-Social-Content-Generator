"""Phase 2: client-created custom reel formats.

The add flow: name → plain-language description → one Claude call builds
a reel-format TEMPLATE → the template is validated against the
placeholder contract (auto-retry once) → a SAMPLE reel is composed for
preview → the client Saves / Regenerates / Discards. Saved formats live
per-user in the vault and appear in the reel format picker automatically
(Phase 1's get_reel_formats merge).

State is carried in context.user_data, mirroring the awaiting_* flags in
message_bot:
- awaiting_format_name  → next message is the format name
- awaiting_format_desc  → next message is the description
- pending_format        → {"name","description","template"} during preview
"""

import json
import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.ui import cancel_markup
from ai_social_content_generator.telegram_bot.users import load_user
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.ui import typing_action
from ai_social_content_generator.reel_formats import (
    custom_format_path,
    get_reel_formats,
    save_custom_format,
    slugify_format_id,
    validate_template_placeholders,
)

logger = logging.getLogger(__name__)

CREATE_SKILL_PATH = Path("src/ai_social_content_generator/create_reel_format/SKILL.md")

FORMAT_NAME_MIN, FORMAT_NAME_MAX = 1, 40
FORMAT_DESC_MIN, FORMAT_DESC_MAX = 10, 1000
MAX_TEMPLATE_ATTEMPTS = 2

# Generic topic/hook for the preview — no real topic is picked at format
# creation time, so seed the template with example values that still let
# it render a representative reel.
SAMPLE_TOPIC = "(example) why most couples avoid the real conversation"
SAMPLE_HEADLINE = "The conversation you keep postponing"


def _strip_template_fences(text: str) -> str:
    """Defensive: the SKILL says output only the template, but strip any
    leading code fence / trailing fence if the model adds them anyway."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _build_sample_context(user_id: int) -> dict | None:
    """Build the contract placeholder dict from the user's REAL analysis,
    with a generic topic+hook. Returns None if analysis is missing."""
    user_data = load_user(user_id)
    if not user_data or "handle" not in user_data:
        return None
    handle = user_data["handle"]
    analysis_path = Path(f"cache/{handle}-analysis.json")
    if not analysis_path.exists():
        return None

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    niche = analysis.get("niche") or user_data.get("niche", "")
    voice = analysis.get("voice", [])
    voice_str = ", ".join(voice) if isinstance(voice, list) else str(voice)
    themes = analysis.get("recurring_themes", [])
    themes_str = (
        "\n".join(f"- {t}" for t in themes) if isinstance(themes, list) else str(themes)
    )

    # Heavy imports (Playwright/IG SDK via compose_carousel) deferred to
    # call time, matching the lazy-import pattern elsewhere.
    from ai_social_content_generator.telegram_bot.actions.profile_skill_creator import (
        build_engagement_digest,
    )
    from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
        build_competitor_section,
    )

    posts_path = Path(f"cache/{handle}-posts.json")
    posts_list = (
        json.loads(posts_path.read_text(encoding="utf-8")) if posts_path.exists() else []
    )
    engagement_digest = build_engagement_digest(posts_list, top_n=3)
    competitor_section = build_competitor_section(user_data.get("competitors", []))

    return {
        "niche": niche,
        "voice_str": voice_str,
        "themes_str": themes_str,
        "engagement_digest": engagement_digest,
        "competitor_section": competitor_section,
        "chosen_topic": SAMPLE_TOPIC,
        "chosen_headline": SAMPLE_HEADLINE,
    }


async def _generate_template(name: str, description: str) -> str | None:
    """One Claude call → a reel-format template (fences stripped). Returns
    None on Claude failure."""
    skill = CREATE_SKILL_PATH.read_text(encoding="utf-8")
    prompt = skill.format(format_name=name, format_description=description)
    reply = await message_claude(prompt)
    raw = getattr(reply, "stdout", None)
    rc = getattr(reply, "returncode", -1)
    if reply is None or rc != 0 or not raw:
        logger.error("create_reel_format: Claude failed reply=%r", reply)
        return None
    return _strip_template_fences(raw)


@require_auth
async def reel_format_add_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """➕ Add format tap: gate on analysis existing, then ask for a name."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # A custom format needs the user's analysis to compose a sample (and
    # every future reel). Fail fast before collecting name+description.
    if _build_sample_context(user_id) is None:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Please run Analyze first before creating a custom format.",
        )
        return

    context.user_data["awaiting_format_name"] = True
    await context.bot.send_message(
        chat_id=chat_id,
        text="Name this format (short, e.g. 'Story flip'):",
        reply_markup=cancel_markup(),
    )


async def format_name_receive(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """message_bot branch for awaiting_format_name."""
    name = (update.message.text or "").strip()
    if not (FORMAT_NAME_MIN <= len(name) <= FORMAT_NAME_MAX):
        await update.message.reply_text(
            f"Name must be {FORMAT_NAME_MIN}-{FORMAT_NAME_MAX} characters. Try again."
        )
        return  # keep the flag set
    context.user_data.pop("awaiting_format_name", None)
    context.user_data["pending_format"] = {"name": name}
    context.user_data["awaiting_format_desc"] = True
    await update.message.reply_text(
        "Describe the format: structure, tone, what happens start to finish. "
        "The more specific, the better.",
        reply_markup=cancel_markup(),
    )


async def format_desc_receive(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """message_bot branch for awaiting_format_desc."""
    desc = (update.message.text or "").strip()
    if not (FORMAT_DESC_MIN <= len(desc) <= FORMAT_DESC_MAX):
        await update.message.reply_text(
            f"Description must be {FORMAT_DESC_MIN}-{FORMAT_DESC_MAX} characters. "
            "Try again."
        )
        return  # keep the flag set
    pending = context.user_data.get("pending_format")
    if not pending:
        context.user_data.pop("awaiting_format_desc", None)
        await update.message.reply_text("Start again from ➕ Add format.")
        return
    context.user_data.pop("awaiting_format_desc", None)
    pending["description"] = desc
    await _generate_and_preview_format(update, context)


INSUFFICIENT_SIGNAL = "INSUFFICIENT_SIGNAL"


async def _typed_generate(name: str, desc: str):
    """Generator for the typed-description origin. Returns
    (status, template): status in {"ok","fail"}."""
    cand = await _generate_template(name, desc)
    return ("fail", None) if cand is None else ("ok", cand)


async def _reel_generate(prompt: str, image_dir: str):
    """Generator for the reel (vision) origin. Returns (status, template):
    status in {"ok","insufficient","fail"}."""
    reply = await message_claude(prompt, image_dir=image_dir)
    raw = getattr(reply, "stdout", None)
    rc = getattr(reply, "returncode", -1)
    if reply is None or rc != 0 or not raw:
        return "fail", None
    cand = _strip_template_fences(raw)
    if cand.strip() == INSUFFICIENT_SIGNAL:
        return "insufficient", None
    return "ok", cand


def _make_generator(pending: dict):
    """Reconstruct the right generator from a pending_format's origin —
    used by both the initial build and Regenerate."""
    if pending.get("origin") == "reel":
        return lambda: _reel_generate(pending["reel_prompt"], pending["frames_dir"])
    return lambda: _typed_generate(pending["name"], pending["description"])


async def run_format_preview(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, progress: str
) -> None:
    """Shared engine: generate a template (validate, auto-retry once),
    then preview+offer. Reads pending_format (its origin selects the
    generator). Aborts on INSUFFICIENT_SIGNAL or repeated invalidity."""
    chat_id = update.effective_chat.id
    pending = context.user_data.get("pending_format")
    if not pending:
        await context.bot.send_message(
            chat_id=chat_id, text="Start again from ➕ Add format.",
        )
        return

    await context.bot.send_message(chat_id=chat_id, text=progress)
    generate = _make_generator(pending)

    template = None
    for attempt in range(1, MAX_TEMPLATE_ATTEMPTS + 1):
        async with typing_action(context.bot, chat_id):
            status, candidate = await generate()
        if status == "insufficient":
            context.user_data.pop("pending_format", None)
            await context.bot.send_message(
                chat_id=chat_id,
                text="Couldn't analyze this reel into a format (no clear "
                     "structure in the speech or the frames).",
            )
            return
        if status == "ok" and candidate is not None:
            ok, reason = validate_template_placeholders(candidate)
            if ok:
                template = candidate
                break
            logger.warning(
                "create_reel_format: invalid template (attempt %d): %s",
                attempt, reason,
            )
        if attempt < MAX_TEMPLATE_ATTEMPTS:
            await context.bot.send_message(
                chat_id=chat_id, text="The format came out malformed, regenerating...",
            )

    if template is None:
        context.user_data.pop("pending_format", None)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Couldn't build a valid format. Try a different description "
                 "or reel.",
        )
        return

    pending["template"] = template
    await _preview_and_offer(update, context)


async def _preview_and_offer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Shared tail: compose a sample reel from the (already validated)
    pending template and offer Save / Regenerate / Discard."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    pending = context.user_data.get("pending_format")
    if not pending or not pending.get("template"):
        await context.bot.send_message(
            chat_id=chat_id, text="Start again from ➕ Add format.",
        )
        return

    name = pending["name"]
    template = pending["template"]

    # Compose a sample reel for preview using the real analysis + generic
    # topic/hook. A valid template can still be saved if the sample call
    # fails (the failure is transient, not a template defect).
    ctx = _build_sample_context(user_id)
    sample_text = None
    if ctx is not None:
        async with typing_action(context.bot, chat_id):
            reply = await message_claude(template.format(**ctx))
        raw = getattr(reply, "stdout", None)
        rc = getattr(reply, "returncode", -1)
        if reply is not None and rc == 0 and raw:
            marker = "## Attribution"
            i = raw.find(marker)
            sample_text = (raw[:i].rstrip() if i != -1 else raw).strip()

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💾 Save format", callback_data="format_save")],
        [InlineKeyboardButton("🔄 Regenerate", callback_data="format_regen")],
        [InlineKeyboardButton("🗑 Discard", callback_data="format_discard")],
    ])
    if sample_text:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Here's a sample reel in your '{name}' format:\n\n{sample_text}",
            reply_markup=markup,
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"Your '{name}' format looks valid, but I couldn't render a "
                "sample just now. Save to try it, or Regenerate."
            ),
            reply_markup=markup,
        )


async def _generate_and_preview_format(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Typed-description origin entry: tag origin and run the shared
    engine."""
    pending = context.user_data.get("pending_format")
    if pending is not None:
        pending["origin"] = "typed"
    await run_format_preview(
        update, context, progress="🛠 Building your format, ~30-60 sec...",
    )


@require_auth
async def format_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    pending = context.user_data.get("pending_format")
    if not pending or not pending.get("template"):
        await context.bot.send_message(
            chat_id=chat_id, text="Nothing to save — start from ➕ Add format.",
        )
        return

    existing = {f["id"] for f in get_reel_formats(user_id)}
    fid = slugify_format_id(pending["name"], existing)
    record = {
        "id": fid,
        "name": pending["name"],
        "emoji": "🎬",
        "description": pending["name"],
        "source": "custom",
        "skill_template_path": str(custom_format_path(user_id, fid)),
        # NO convert_template_path — custom formats are compose-only.
    }
    save_custom_format(user_id, record, pending["template"])
    context.user_data.pop("pending_format", None)
    logger.info("Saved custom reel format id=%s for user_id=%s", fid, user_id)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"💾 Saved '{record['name']}' — it's now in your reel format picker.",
    )


@require_auth
async def format_regen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    pending = context.user_data.get("pending_format")
    if not pending:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Nothing to regenerate — start from ➕ Add format.",
        )
        return
    # Branch on origin: a reel-sourced pending must regen via the vision
    # analysis (frames still on disk), NOT the typed generator.
    if pending.get("origin") == "reel":
        progress = "🧬 Re-analyzing this reel into a format, ~30-60 sec..."
    else:
        progress = "🛠 Rebuilding your format, ~30-60 sec..."
    await run_format_preview(update, context, progress=progress)


@require_auth
async def format_discard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("pending_format", None)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Discarded.",
    )

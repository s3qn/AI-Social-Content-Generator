"""Scheduled carousel posts: vault schema, the firing job, the startup
rebuild, and the main-menu manage view.

Design mirrors scheduler.py (reminders): jobs live in PTB's in-memory
JobQueue, and the source of truth is the vault. On boot,
rebuild_scheduled_posts_on_startup re-registers a run_once for every
still-pending post — without it, a restart silently drops every
scheduled post.

The firing path (publish_scheduled_callback) reads ONLY the persisted
record, never session state (there is none days later). It calls
compose_carousel._publish_carousel_from_data, which is arg-only.
"""

import logging
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import (
    iter_all_users,
    load_user,
    save_user,
)

logger = logging.getLogger(__name__)

# One fixed zone for all scheduling. One-line changeable.
SCHEDULE_TZ = ZoneInfo("Asia/Jerusalem")
# A post whose time passed by <= GRACE while the bot was offline is
# published on boot; beyond it, marked "missed" (never post badly-stale).
GRACE_SECONDS = 3 * 3600
# IG's practical scheduling horizon — reject absurd far-future dates.
SCHEDULE_MAX_DAYS = 75
# IG cap: 25 published API posts / 24h / account (Reels+Stories share it).
MAX_PUBLISHED_24H = 25

SCHEDULED_DIR = Path("cache/scheduled")
JOB_PREFIX = "sched_"


# ----------------------------------------------------------------------
# Vault helpers (pure — import only users.py).
# ----------------------------------------------------------------------

def add_scheduled_post(user_data: dict, record: dict) -> dict:
    user_data.setdefault("scheduled_posts", []).append(record)
    return user_data


def get_scheduled_posts(user_data: dict) -> list[dict]:
    return user_data.get("scheduled_posts", [])


def get_scheduled_post(user_data: dict, post_id: str) -> dict | None:
    for rec in get_scheduled_posts(user_data):
        if rec.get("id") == post_id:
            return rec
    return None


def update_status(user_data: dict, post_id: str, status: str, **extra) -> bool:
    """Set status (+ optional extra fields like published_ts) on a record.
    Returns True if found."""
    rec = get_scheduled_post(user_data, post_id)
    if rec is None:
        return False
    rec["status"] = status
    rec.update(extra)
    return True


def remove_scheduled_post(user_data: dict, post_id: str) -> bool:
    posts = user_data.get("scheduled_posts", [])
    for i, rec in enumerate(posts):
        if rec.get("id") == post_id:
            posts.pop(i)
            return True
    return False


def new_post_id() -> str:
    return uuid.uuid4().hex[:12]


# ----------------------------------------------------------------------
# Time helpers.
# ----------------------------------------------------------------------

def parse_schedule_input(text: str) -> datetime | None:
    """Parse 'DD/MM/YYYY HH:MM' as Asia/Jerusalem. Returns an aware
    datetime, or None on bad format."""
    try:
        naive = datetime.strptime(text.strip(), "%d/%m/%Y %H:%M")
    except ValueError:
        return None
    return naive.replace(tzinfo=SCHEDULE_TZ)


def format_ts(ts: int) -> str:
    """Epoch → 'Thu 25/06 09:00' in the schedule zone."""
    return datetime.fromtimestamp(ts, SCHEDULE_TZ).strftime("%a %d/%m %H:%M")


# ----------------------------------------------------------------------
# Job registration.
# ----------------------------------------------------------------------

def job_name(uid: int, post_id: str) -> str:
    """Unique per post so cancel/rebuild target exactly one job."""
    return f"{JOB_PREFIX}{uid}_{post_id}"


def schedule_post_job(
    application: Application, uid: int, record: dict, *, when=None
) -> None:
    """Register the run_once that fires publish_scheduled_callback. `when`
    defaults to the record's scheduled_ts (aware UTC datetime); pass a
    seconds-delay to fire a recently-missed post 'now'."""
    job_queue = application.job_queue
    if job_queue is None:
        logger.error("JobQueue is None — cannot schedule post %s", record.get("id"))
        return
    if when is None:
        when = datetime.fromtimestamp(record["scheduled_ts"], tz=timezone.utc)
    post_id = record["id"]
    job_queue.run_once(
        callback=publish_scheduled_callback,
        when=when,
        data={"uid": uid, "post_id": post_id},
        name=job_name(uid, post_id),
    )
    logger.info("Scheduled post job %s for uid=%s when=%s", post_id, uid, when)


def cancel_post_job(application: Application, uid: int, post_id: str) -> int:
    """Remove the job for one post. Returns count removed."""
    job_queue = application.job_queue
    if job_queue is None:
        return 0
    jobs = job_queue.get_jobs_by_name(job_name(uid, post_id))
    for job in jobs:
        job.schedule_removal()
    return len(jobs)


# ----------------------------------------------------------------------
# Firing job.
# ----------------------------------------------------------------------

def _count_published_last_24h(user_data: dict) -> int:
    cutoff = time.time() - 86400
    return sum(
        1
        for r in get_scheduled_posts(user_data)
        if r.get("status") == "published" and (r.get("published_ts") or 0) >= cutoff
    )


def _slide_paths_for(image_dir: str) -> list[Path]:
    d = Path(image_dir)
    if not d.exists():
        return []
    return sorted(d.glob("slide_*.png"))


async def publish_scheduled_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback. Publishes ONE scheduled carousel from its
    persisted record. No session state — everything comes from the vault."""
    data = context.job.data
    uid = data["uid"]
    post_id = data["post_id"]

    user_data = load_user(uid)
    if user_data is None:
        logger.warning("publish_scheduled: no vault for uid=%s", uid)
        return

    rec = get_scheduled_post(user_data, post_id)
    if rec is None or rec.get("status") != "pending":
        # Cancelled or already handled — nothing to do.
        logger.info("publish_scheduled: post %s not pending, skipping", post_id)
        return

    async def _notify(text: str) -> None:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
        except Exception as e:
            logger.warning("publish_scheduled: notify failed uid=%s: %s", uid, e)

    def _mark(status: str, **extra) -> None:
        update_status(user_data, post_id, status, **extra)
        save_user(uid, user_data)

    # Soft daily-cap guard so a week's batch fails loudly, not mid-publish.
    if _count_published_last_24h(user_data) >= MAX_PUBLISHED_24H:
        _mark("failed")
        await _notify(
            "The daily publishing limit was reached, so a scheduled post "
            "wasn't sent. Try again tomorrow."
        )
        return

    slide_paths = _slide_paths_for(rec.get("image_dir", ""))
    if not slide_paths:
        _mark("failed")
        await _notify(
            "Couldn't publish your scheduled carousel — its images are no "
            "longer available."
        )
        return

    # Local import: compose_carousel pulls heavy modules (Playwright, IG
    # SDK); importing at module top would create a cycle. The publisher
    # reads its own tokens + autopost toggles, so FB rides in for free.
    from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
        _publish_carousel_from_data,
        summarize_publish_result,
    )

    result = await _publish_carousel_from_data(
        user_id=uid,
        slide_paths=slide_paths,
        caption=rec.get("caption", ""),
        hashtags=rec.get("hashtags", ""),
    )
    any_ok, summary = summarize_publish_result(result)
    when = format_ts(rec.get("scheduled_ts", 0))

    # A scheduled post is terminal either way (its images never re-fire), so
    # delete them in both branches to keep cache/scheduled from growing.
    shutil.rmtree(rec.get("image_dir", ""), ignore_errors=True)
    if any_ok:
        # Partial success counts as published — at least one platform posted.
        _mark("published", published_ts=int(time.time()))
        await _notify(f"✅ Your scheduled post ({when}):\n{summary}")
        logger.info("Scheduled publish OK uid=%s post=%s", uid, post_id)
    else:
        _mark("failed")
        await _notify(
            f"⚠️ Your scheduled post ({when}) couldn't be published:\n{summary}"
        )
        logger.warning("Scheduled publish failed uid=%s post=%s", uid, post_id)


# ----------------------------------------------------------------------
# Startup rebuild — the function whose absence = vanished posts.
# ----------------------------------------------------------------------

async def rebuild_scheduled_posts_on_startup(application: Application) -> None:
    """Re-register a run_once for every still-pending post. Recently-missed
    posts (<= GRACE) fire on boot; older ones are marked 'missed' and the
    user is notified — never silently dropped, never posted badly stale."""
    logger.info("Rebuilding scheduled posts from vault...")
    now = time.time()
    future = grace = missed = 0

    for uid, user_data in iter_all_users():
        changed = False
        for rec in user_data.get("scheduled_posts", []):
            if rec.get("status") != "pending":
                continue
            ts = rec.get("scheduled_ts", 0)
            delay = now - ts
            if ts > now:
                schedule_post_job(application, uid, rec)
                future += 1
            elif delay <= GRACE_SECONDS:
                # Recently missed — fire a few seconds out.
                schedule_post_job(application, uid, rec, when=5)
                grace += 1
            else:
                rec["status"] = "missed"
                changed = True
                missed += 1
                try:
                    await application.bot.send_message(
                        chat_id=uid,
                        text=(
                            "⏰ A scheduled post's time passed while the bot was "
                            "offline, so it wasn't published. Re-create it from "
                            "the carousel when you're ready."
                        ),
                    )
                except Exception as e:
                    logger.warning("missed-notify failed uid=%s: %s", uid, e)
        if changed:
            save_user(uid, user_data)

    logger.info(
        "Rebuilt scheduled posts: %d future, %d grace-fire, %d missed",
        future, grace, missed,
    )


# ----------------------------------------------------------------------
# Manage view (main menu).
# ----------------------------------------------------------------------

@require_auth
async def scheduled_posts_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """List this user's pending posts sorted by time, each with a cancel
    button. Also handles the Back button (^scheduled_back$)."""
    query = update.callback_query
    await query.answer()

    if query.data == "scheduled_back":
        from ai_social_content_generator.telegram_bot.actions.menu import (
            _main_menu_keyboard,
        )
        await query.edit_message_text(
            "What would you like to do?",
            reply_markup=_main_menu_keyboard(),
        )
        return

    user_id = update.effective_user.id
    user_data = load_user(user_id)
    pending = [
        r for r in get_scheduled_posts(user_data or {})
        if r.get("status") == "pending"
    ]
    pending.sort(key=lambda r: r.get("scheduled_ts", 0))

    if not pending:
        keyboard = [[InlineKeyboardButton("← Back", callback_data="scheduled_back")]]
        await query.edit_message_text(
            "📅 No scheduled posts.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    lines = ["📅 Your scheduled posts:\n"]
    keyboard: list[list[InlineKeyboardButton]] = []
    for rec in pending:
        when = format_ts(rec.get("scheduled_ts", 0))
        caption = (rec.get("caption") or "").strip().replace("\n", " ")
        preview = caption[:30] + ("…" if len(caption) > 30 else "")
        lines.append(f"• {when} — '{preview}'")
        keyboard.append([InlineKeyboardButton(
            f"🗑 Cancel {when}", callback_data=f"sched_cancel_{rec['id']}"
        )])
    keyboard.append([InlineKeyboardButton("← Back", callback_data="scheduled_back")])

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def scheduled_cancel_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Cancel a pending post: remove the job AND the record, delete its
    images. Removing both is essential — a record-only cancel still fires."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    post_id = query.data.removeprefix("sched_cancel_")
    user_data = load_user(user_id)
    if user_data is None:
        await query.edit_message_text("No account info found.")
        return

    rec = get_scheduled_post(user_data, post_id)
    if rec is not None:
        cancel_post_job(context.application, user_id, post_id)
        shutil.rmtree(rec.get("image_dir", ""), ignore_errors=True)
        remove_scheduled_post(user_data, post_id)
        save_user(user_id, user_data)
        logger.info("Cancelled scheduled post %s for uid=%s", post_id, user_id)

    await scheduled_posts_show(update, context)

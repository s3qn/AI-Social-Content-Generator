import json
import logging
import re
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from ai_social_content_generator.telegram_bot.auth import require_auth
from ai_social_content_generator.telegram_bot.users import (
    add_headlines_to_topic,
    load_user,
    save_user,
)
from ai_social_content_generator.telegram_bot.call_claude import message_claude
from ai_social_content_generator.telegram_bot.actions.compose_carousel import (
    build_competitor_section,
)

logger = logging.getLogger(__name__)

SKILL_PATH = Path("src/ai_social_content_generator/generate_headlines/SKILL.md")
MIN_PARSED_HOOKS = 5


@require_auth
async def generate_headlines_for_all(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
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
            text="Please run Analyze first before generating headlines.",
        )
        return

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    voice = analysis.get("voice", [])
    voice_str = ", ".join(voice) if isinstance(voice, list) else str(voice)
    niche = analysis.get("niche") or user_data.get("niche", "")

    competitors = user_data.get("competitors", [])
    competitor_section = build_competitor_section(competitors)

    empty_topics = [
        t for t in user_data.get("topics", [])
        if not t.get("headlines")
    ]
    if not empty_topics:
        await query.edit_message_text("All topics already have headlines.")
        return

    await query.edit_message_text(
        f"Generating headlines for {len(empty_topics)} topic(s). "
        f"About {len(empty_topics) * 30} seconds total."
    )

    skill_template = SKILL_PATH.read_text(encoding="utf-8")

    success_count = 0
    failure_count = 0

    for topic in empty_topics:
        core_idea = topic.get("core_idea", "")
        topic_id = topic.get("id", "")
        prompt = skill_template.format(
            topic=core_idea,
            niche=niche,
            voice_str=voice_str,
            competitor_section=competitor_section,
        )

        claude_reply = await message_claude(prompt)
        raw_output = getattr(claude_reply, "stdout", "") or ""
        returncode = getattr(claude_reply, "returncode", -1)

        if returncode != 0 or not raw_output:
            logger.error(
                "Headlines: Claude failed for topic_id=%s handle=%s reply=%r",
                topic_id, handle, claude_reply,
            )
            failure_count += 1
            continue

        idx = raw_output.find("## Hooks")
        if idx == -1:
            logger.error(
                "Headlines: '## Hooks' section missing for topic_id=%s raw=%r",
                topic_id, raw_output,
            )
            failure_count += 1
            continue

        hooks_text = raw_output[idx + len("## Hooks"):]
        parsed = re.findall(r"^\s*\d+\.\s*(.+?)\s*$", hooks_text, re.MULTILINE)
        hooks = [h.strip() for h in parsed if h.strip()]

        if len(hooks) < MIN_PARSED_HOOKS:
            logger.error(
                "Headlines: parsed too few hooks (%d) for topic_id=%s raw=%r",
                len(hooks), topic_id, raw_output,
            )
            failure_count += 1
            continue

        add_headlines_to_topic(user_data, topic_id, hooks)
        success_count += 1

        preview = core_idea[:50]
        suffix = "..." if len(core_idea) > 50 else ""
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✓ {preview}{suffix} — {len(hooks)} hooks",
        )

    save_user(user_id, user_data)

    summary = f"✨ Done. Generated headlines for {success_count} topic(s)."
    if failure_count > 0:
        summary += f"\n⚠️ {failure_count} topic(s) failed."
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=summary,
    )

    logger.info(
        "Headlines complete for handle=%s success=%d failure=%d",
        handle, success_count, failure_count,
    )

    from ai_social_content_generator.telegram_bot.actions.menu import (
        brainstorm_submenu_show,
    )
    await brainstorm_submenu_show(update, context)

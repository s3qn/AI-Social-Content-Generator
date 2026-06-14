"""Reel formats as DATA (Phase 1).

Reel formats used to be hardcoded in ~5 places (SKILL path constants,
three picker keyboards, dispatch branches). They are now a list of
records the code reads from. Phase 1 returns only the two built-ins,
pointing at the EXISTING (unmoved, unchanged) SKILL files — behavior is
identical to before.

Phase 2 adds per-user custom formats: get_reel_formats now merges the
user's vault formats after the built-ins, and the create flow validates
+ stores them. Phase 3 will build records from viral-transcript analysis
through the same validate/store path.

load_user is imported at module top (users.py imports only stdlib, so no
cycle).
"""

import re
from pathlib import Path

from ai_social_content_generator.telegram_bot.users import load_user

CUSTOM_FORMATS_DIR = Path("cache/reel_formats")

# The EXACT placeholder set compose_reel_from_picked fills via .format().
# A generated template missing one, or carrying a foreign {token}, would
# KeyError on every future reel of that format — so we validate before
# allowing save.
REQUIRED_PLACEHOLDERS = {
    "niche", "voice_str", "themes_str", "chosen_topic",
    "chosen_headline", "engagement_digest", "competitor_section",
}

BUILTIN_REEL_FORMATS = [
    {
        "id": "talking_head",
        "name": "Talking head",
        "emoji": "🎤",
        "description": "You speak to the camera. More personal but more effort.",
        "skill_template_path": "src/ai_social_content_generator/compose_reel/SKILL.md",
        "convert_template_path": "src/ai_social_content_generator/convert_carousel_reel/SKILL.md",
        "source": "builtin",
    },
    {
        "id": "text_overlay",
        "name": "Text overlay",
        "emoji": "📝",
        "description": "Viewers READ text over simple b-roll. No speaking. Low effort. (Went viral on your account.)",
        "skill_template_path": "src/ai_social_content_generator/compose_reel_text_overlay/SKILL.md",
        "convert_template_path": "src/ai_social_content_generator/convert_carousel_reel_text_overlay/SKILL.md",
        "source": "builtin",
    },
]


def get_reel_formats(user_id: int) -> list[dict]:
    """Built-ins + this user's custom formats (vault). Built-ins first."""
    user_data = load_user(user_id)
    customs = user_data.get("reel_formats", []) if user_data else []
    return list(BUILTIN_REEL_FORMATS) + list(customs)


def get_reel_format(user_id: int, format_id: str) -> dict | None:
    for fmt in get_reel_formats(user_id):
        if fmt["id"] == format_id:
            return fmt
    return None


def load_format_template(fmt: dict, *, convert: bool = False) -> str:
    """Read the .md template the record points at. `convert=True` uses the
    carousel→reel template. The path may be a repo SKILL (built-ins) or a
    cache file (custom formats) — same code path."""
    key = "convert_template_path" if convert else "skill_template_path"
    path = fmt.get(key)
    if not path:
        raise FileNotFoundError(f"format {fmt.get('id')} has no {key}")
    return Path(path).read_text(encoding="utf-8")


def slugify_format_id(name: str, existing_ids: set[str]) -> str:
    """Short, fs-safe, callback-safe (<40 chars) unique id from a name.
    Non-ASCII (e.g. Hebrew) collapses to '_' and falls back to 'format'."""
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30] or "format"
    fid = base
    n = 2
    while fid in existing_ids:
        fid = f"{base}_{n}"
        n += 1
    return fid


def validate_template_placeholders(template: str) -> tuple[bool, str]:
    """All required placeholders present AND no foreign {tokens}. Returns
    (ok, reason). Foreign tokens would KeyError on .format() at compose."""
    found = set(re.findall(r"\{(\w+)\}", template))
    missing = REQUIRED_PLACEHOLDERS - found
    foreign = found - REQUIRED_PLACEHOLDERS
    if missing:
        return False, f"missing placeholders: {sorted(missing)}"
    if foreign:
        return False, f"unknown placeholders: {sorted(foreign)}"
    return True, ""


def custom_format_path(user_id: int, format_id: str) -> Path:
    return CUSTOM_FORMATS_DIR / str(user_id) / f"{format_id}.md"


def save_custom_format(user_id: int, record: dict, template: str) -> None:
    """Write the .md template and append the record to the user's vault."""
    path = custom_format_path(user_id, record["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template, encoding="utf-8")
    from ai_social_content_generator.telegram_bot.users import save_user
    user_data = load_user(user_id) or {}
    user_data.setdefault("reel_formats", []).append(record)
    save_user(user_id, user_data)

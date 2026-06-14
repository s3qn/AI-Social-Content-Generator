"""Reel formats as DATA (Phase 1).

Reel formats used to be hardcoded in ~5 places (SKILL path constants,
three picker keyboards, dispatch branches). They are now a list of
records the code reads from. Phase 1 returns only the two built-ins,
pointing at the EXISTING (unmoved, unchanged) SKILL files — behavior is
identical to before.

Phase 2 will append per-user custom formats from the vault; Phase 3 will
build format records from viral-transcript analysis. The resolver and
template loader are already shaped for a path that points at either a
repo SKILL (built-ins) or a cache file (future customs).

Kept dependency-light on purpose to avoid import cycles. Phase 2 will
import load_user here to append the user's vault formats; until it's
actually called, the import is omitted so it can't lint as unused.
(users.py imports only stdlib, so no cycle exists when it's added.)
"""

from pathlib import Path

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
    """Built-in formats now. Phase 2 will append the user's vault customs:
    load_user(user_id).get('reel_formats', []). Order: built-ins first."""
    return list(BUILTIN_REEL_FORMATS)


def get_reel_format(user_id: int, format_id: str) -> dict | None:
    for fmt in get_reel_formats(user_id):
        if fmt["id"] == format_id:
            return fmt
    return None


def load_format_template(fmt: dict, *, convert: bool = False) -> str:
    """Read the .md template the record points at. `convert=True` uses the
    carousel→reel template. Phase 1: path is a repo file. Phase 2: a path
    may point at cache/reel_formats/<uid>/<id>.md — same code path, no
    change needed."""
    key = "convert_template_path" if convert else "skill_template_path"
    path = fmt.get(key)
    if not path:
        raise FileNotFoundError(f"format {fmt.get('id')} has no {key}")
    return Path(path).read_text(encoding="utf-8")

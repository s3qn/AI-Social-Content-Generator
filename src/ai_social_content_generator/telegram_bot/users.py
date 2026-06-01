from pathlib import Path
import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

USERS_DIR = Path('users')
MAX_TOPICS = 30
MAX_VIRAL_KEYWORDS = 15

def user_path(user_id: int) -> Path:
    return Path(USERS_DIR, f'{user_id}.json')

def is_onboarded(user_id: int) -> bool:
    return user_path(user_id).exists()

def load_user(user_id: int) -> None | dict:
    path = user_path(user_id)

    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("competitors", [])
    data.setdefault("topics", [])
    data.setdefault("viral_keywords", [])
    data.setdefault("reminder_schedule", {"enabled": False, "slot": None})
    return data

def save_user(user_id: int, data: dict) -> None:
    USERS_DIR.mkdir(exist_ok=True)
    path = user_path(user_id)
    data["user_id"] = user_id
    data["onboarded_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def add_topic(user_data: dict, core_idea: str) -> dict:
    topic = {
        "id": f"topic_{uuid.uuid4().hex[:12]}",
        "core_idea": core_idea,
        "headlines": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    user_data["topics"].append(topic)
    _prune_topics(user_data)
    return user_data


def add_viral_keyword(user_data: dict, keyword: str) -> dict | None:
    """Add a viral search keyword. Returns the new dict, or None on
    duplicate, empty input, or cap reached."""
    keyword = keyword.strip()
    if not keyword:
        return None
    keywords = user_data.setdefault("viral_keywords", [])
    for existing in keywords:
        if existing["text"].lower() == keyword.lower():
            return None
    if len(keywords) >= MAX_VIRAL_KEYWORDS:
        return None
    new_kw = {
        "id": f"kw_{uuid.uuid4().hex[:12]}",
        "text": keyword,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    keywords.append(new_kw)
    return new_kw


def remove_viral_keyword(user_data: dict, keyword_id: str) -> bool:
    """Remove by id. Returns True if removed."""
    keywords = user_data.get("viral_keywords", [])
    for i, kw in enumerate(keywords):
        if kw.get("id") == keyword_id:
            keywords.pop(i)
            return True
    return False


def heal_duplicate_topic_ids(user_data: dict) -> bool:
    """Give a fresh uuid to any topic whose id duplicates an earlier one.
    Returns True if anything was changed (caller should save_user)."""
    seen: set[str] = set()
    changed = False
    for topic in user_data.get("topics", []):
        tid = topic.get("id")
        if not tid or tid in seen:
            topic["id"] = f"topic_{uuid.uuid4().hex[:12]}"
            changed = True
        seen.add(topic["id"])
    return changed


def add_headlines_to_topic(user_data: dict, topic_id: str, headlines: list[str]) -> dict:
    for topic in user_data["topics"]:
        if topic["id"] == topic_id:
            for headline in headlines:
                topic["headlines"].append({"text": headline, "used": False})
            return user_data
    logger.warning("add_headlines_to_topic: topic_id %s not found", topic_id)
    return user_data


def mark_headline_used(user_data: dict, topic_id: str, headline_text: str) -> dict:
    for topic in user_data["topics"]:
        if topic["id"] == topic_id:
            for headline in topic["headlines"]:
                if headline["text"] == headline_text:
                    headline["used"] = True
                    headline["used_at"] = datetime.now(timezone.utc).isoformat()
                    return user_data
            logger.warning("mark_headline_used: headline %r not found in topic %s", headline_text, topic_id)
            return user_data
    logger.warning("mark_headline_used: topic_id %s not found", topic_id)
    return user_data


def get_unused_headlines(user_data: dict) -> list[dict]:
    result: list[dict] = []
    for topic in user_data["topics"]:
        for headline in topic["headlines"]:
            if not headline["used"]:
                result.append({
                    "topic_id": topic["id"],
                    "core_idea": topic["core_idea"],
                    "headline_text": headline["text"],
                })
    return result


def set_reminder_schedule(
    user_data: dict,
    enabled: bool,
    slot: str | None = None,
) -> dict:
    """Set the reminder schedule. When enabled, slot must be 'morning'
    or 'evening'. When disabled, slot is forced to None."""
    if enabled and slot not in ("morning", "evening"):
        raise ValueError(
            f"slot must be 'morning' or 'evening' when enabled=True, got {slot!r}"
        )
    user_data["reminder_schedule"] = {
        "enabled": enabled,
        "slot": slot if enabled else None,
    }
    return user_data["reminder_schedule"]


def get_reminder_schedule(user_data: dict) -> dict:
    """Returns {enabled: bool, slot: str | None}."""
    return user_data.get(
        "reminder_schedule",
        {"enabled": False, "slot": None},
    )


def iter_all_users() -> list[tuple[int, dict]]:
    """Returns (user_id_int, user_data_dict) tuples for every user file.
    Used by the scheduler on startup to rebuild jobs."""
    users_dir = Path(__file__).resolve().parents[3] / "users"
    results: list[tuple[int, dict]] = []
    if not users_dir.exists():
        return results
    for path in users_dir.glob("*.json"):
        try:
            user_id = int(path.stem)
        except ValueError:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            results.append((user_id, data))
        except Exception as e:
            logger.warning("Failed to load user %s: %s", path, e)
    return results


def topic_is_used(topic: dict) -> bool:
    """A topic counts as used iff it has at least one headline AND every
    headline is marked used. Empty-headlines topics are NOT used (they're
    eligible for brief surfacing and for eviction in pruning)."""
    headlines = topic.get("headlines") or []
    return bool(headlines) and all(h.get("used") for h in headlines)


def get_unused_topics(user_data: dict) -> list[dict]:
    """Topics not fully used — eligible for the morning brief. A topic is
    eligible if it has no headlines yet OR has at least one unused headline."""
    return [t for t in user_data.get("topics", []) if not topic_is_used(t)]


def _prune_topics(user_data: dict) -> dict:
    topics = user_data["topics"]
    if len(topics) <= MAX_TOPICS:
        return user_data

    unused_with_idx = [(i, t) for i, t in enumerate(topics) if not topic_is_used(t)]
    unused_with_idx.sort(key=lambda pair: pair[1]["generated_at"])

    to_remove: set[int] = set()
    for idx, _ in unused_with_idx:
        if len(topics) - len(to_remove) <= MAX_TOPICS:
            break
        to_remove.add(idx)

    if to_remove:
        topics[:] = [t for i, t in enumerate(topics) if i not in to_remove]

    if len(topics) > MAX_TOPICS:
        ordered = sorted(enumerate(topics), key=lambda pair: pair[1]["generated_at"])
        excess = len(topics) - MAX_TOPICS
        drop_indices = {idx for idx, _ in ordered[:excess]}
        topics[:] = [t for i, t in enumerate(topics) if i not in drop_indices]

    return user_data

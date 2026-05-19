from pathlib import Path
import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

USERS_DIR = Path('users')
MAX_TOPICS = 30

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
    return data

def save_user(user_id: int, data: dict) -> None:
    USERS_DIR.mkdir(exist_ok=True)
    path = user_path(user_id)
    data["user_id"] = user_id
    data["onboarded_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def add_topic(user_data: dict, core_idea: str) -> dict:
    timestamp_ms = int(time.time() * 1000)
    topic = {
        "id": f"topic_{timestamp_ms}",
        "core_idea": core_idea,
        "headlines": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    user_data["topics"].append(topic)
    _prune_topics(user_data)
    return user_data


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


def _prune_topics(user_data: dict) -> dict:
    topics = user_data["topics"]
    if len(topics) <= MAX_TOPICS:
        return user_data

    def is_used(topic: dict) -> bool:
        headlines = topic["headlines"]
        return bool(headlines) and all(h["used"] for h in headlines)

    unused_with_idx = [(i, t) for i, t in enumerate(topics) if not is_used(t)]
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

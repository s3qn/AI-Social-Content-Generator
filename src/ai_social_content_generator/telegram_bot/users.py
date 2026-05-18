from pathlib import Path
import json
from datetime import datetime, timezone

USERS_DIR = Path('users')

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
    return data

def save_user(user_id: int, data: dict) -> None:
    USERS_DIR.mkdir(exist_ok=True)
    path = user_path(user_id)
    data["user_id"] = user_id
    data["onboarded_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


import os
from functools import wraps

from dotenv import find_dotenv, load_dotenv

"""Authorization for the Telegram bot. Whitelisted to selected few.
The list of allowed Telegram user IDs is loaded from the
TELEGRAM_ALLOWED_CHAT_IDS env var (comma-separated)."""

load_dotenv(find_dotenv())


def _parse_whitelist(raw: str | None) -> list[int]:
    if not raw:
        return []
    result: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            result.append(int(token))
        except ValueError:
            continue
    return result


USER_WHITELIST: list[int] = _parse_whitelist(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS"))


def require_auth(func):
    @wraps(func)
    async def wrapped(update, context):
        if update.effective_user.id not in USER_WHITELIST:
            return
        return await func(update, context)
    return wrapped
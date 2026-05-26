import os
from functools import wraps

from dotenv import find_dotenv, load_dotenv
from telegram import Update
from telegram.ext import ContextTypes

"""Authorization for the Telegram bot. Whitelisted to selected few.
The list of allowed Telegram user IDs is loaded from the
TELEGRAM_ALLOWED_CHAT_IDS env var (comma-separated)."""

load_dotenv(find_dotenv())


ADMIN_USER_IDS = frozenset({6552355280})  # Sean


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


def require_admin(handler):
    """Decorator: gate a handler to admin user IDs only. Non-admins get
    a generic 'command not recognized' message (don't leak the existence
    of admin commands)."""
    @wraps(handler)
    async def wrapper(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *args,
        **kwargs,
    ):
        user = update.effective_user
        if user is None or user.id not in ADMIN_USER_IDS:
            if update.message:
                await update.message.reply_text(
                    "Sorry, I don't recognize that command."
                )
            return
        return await handler(update, context, *args, **kwargs)
    return wrapper
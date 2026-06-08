"""Per-user Instagram token persistence on top of the existing user vault.

Stored shape inside users/<id>.json:
  "instagram": {
      "token": "<long-lived access token>",
      "expires_at": "2026-08-07T12:00:00+00:00",  # tz-aware ISO
      "ig_account_id": "1784..."
  }

The token itself is NEVER logged anywhere in this module — counts and a
boolean "present" are logged instead. The vault directory (users/) is
gitignored, so files are not at risk of being committed.
"""

import logging
from datetime import datetime, timedelta, timezone

from ai_social_content_generator.telegram_bot.users import load_user, save_user

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def save_token(user_id: int, token: str, expires_in: int, ig_account_id: str) -> None:
    """Persist the long-lived token, computed absolute expiry, and IG id.
    Creates the user file if absent (rare — users normally exist by then)."""
    data = load_user(user_id) or {}
    expires_at = (_now() + timedelta(seconds=int(expires_in))).isoformat()
    data["instagram"] = {
        "token": token,
        "expires_at": expires_at,
        "ig_account_id": str(ig_account_id),
    }
    save_user(user_id, data)
    logger.info(
        "Stored Instagram token for user_id=%s ig_account_id=%s expires_at=%s",
        user_id, ig_account_id, expires_at,
    )


def get_token(user_id: int) -> dict | None:
    """Return the stored {token, expires_at, ig_account_id} dict, or None."""
    data = load_user(user_id)
    if not data:
        return None
    ig = data.get("instagram")
    if not ig or not ig.get("token"):
        return None
    return ig


def is_expired_or_soon(user_id: int, within_days: int = 7) -> bool:
    """True iff there's a token and it expires within `within_days` from
    now (or is already past expiry). False if no token at all."""
    ig = get_token(user_id)
    if not ig:
        return False
    raw = ig.get("expires_at")
    if not raw:
        return True
    try:
        expires_at = datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("Bad expires_at on user_id=%s: %r", user_id, raw)
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at - _now() <= timedelta(days=within_days)


def clear_token(user_id: int) -> None:
    """Remove the Instagram block from the user file (revoke / 401 path)."""
    data = load_user(user_id)
    if not data or "instagram" not in data:
        return
    data.pop("instagram", None)
    save_user(user_id, data)
    logger.info("Cleared Instagram token for user_id=%s", user_id)

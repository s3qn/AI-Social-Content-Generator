"""Per-user Facebook Page token persistence on top of the user vault.
Mirrors instagram/token_store.py but writes a SEPARATE `facebook` block.

Stored shape inside users/<id>.json:
  "facebook": {
      "page_token": "<never-expiring Page access token>",
      "page_id": "1234567890",
      "page_name": "My Page",
      "connected_ts": 1718900000
  }

Page tokens derived from a long-lived user token never expire, so there is
NO expiry tracking and NO refresh job. The token is NEVER logged.
"""

import logging
import time

from ai_social_content_generator.telegram_bot.users import load_user, save_user

logger = logging.getLogger(__name__)


def save_fb_token(
    user_id: int, page_token: str, page_id: str, page_name: str = ""
) -> None:
    """Persist the Page token + id under the `facebook` namespace. Separate
    from the `instagram` block so the two never collide."""
    data = load_user(user_id) or {}
    data["facebook"] = {
        "page_token": page_token,
        "page_id": str(page_id),
        "page_name": page_name,
        "connected_ts": int(time.time()),
    }
    save_user(user_id, data)
    logger.info(
        "Stored Facebook Page token for user_id=%s page_id=%s name=%r",
        user_id, page_id, page_name,
    )


def get_fb_token(user_id: int) -> dict | None:
    """Return {page_token, page_id, page_name, connected_ts}, or None."""
    data = load_user(user_id)
    if not data:
        return None
    fb = data.get("facebook")
    if not fb or not fb.get("page_token"):
        return None
    return fb


def clear_fb_token(user_id: int) -> None:
    """Remove the Facebook block (revoke / 401 path)."""
    data = load_user(user_id)
    if not data or "facebook" not in data:
        return
    data.pop("facebook", None)
    save_user(user_id, data)
    logger.info("Cleared Facebook token for user_id=%s", user_id)

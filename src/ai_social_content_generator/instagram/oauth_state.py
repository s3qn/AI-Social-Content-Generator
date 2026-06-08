"""Single-use OAuth state mapping. The callback is a public endpoint, so
each Connect tap mints a fresh random state, we remember which user_id
it belongs to, and the callback rejects anything that doesn't match a
live pending entry.

In-memory only. The bot is single-process; if it restarts, in-flight
authorize links are invalidated, which is the correct behavior (user
just taps Connect again)."""

import logging
import secrets
import time

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 10 * 60

_pending: dict[str, tuple[int, float]] = {}


def _gc() -> None:
    now = time.monotonic()
    expired = [s for s, (_, ts) in _pending.items() if now - ts > STATE_TTL_SECONDS]
    for s in expired:
        _pending.pop(s, None)


def issue_state(user_id: int) -> str:
    """Mint a random url-safe state and remember which user it's for.
    GC stale entries as a side effect so the dict can't grow forever."""
    _gc()
    state = secrets.token_urlsafe(32)
    _pending[state] = (user_id, time.monotonic())
    logger.info("Issued OAuth state for user_id=%s (pending=%d)", user_id, len(_pending))
    return state


def consume_state(state: str) -> int | None:
    """Resolve the user_id this state was issued to and DELETE the entry
    (single-use). Returns None if state is unknown, expired, or empty —
    the callback MUST treat any None as a rejection."""
    if not state:
        return None
    _gc()
    entry = _pending.pop(state, None)
    if entry is None:
        return None
    user_id, ts = entry
    if time.monotonic() - ts > STATE_TTL_SECONDS:
        return None
    return user_id

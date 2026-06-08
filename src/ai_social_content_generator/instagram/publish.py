"""Instagram carousel publish — pure Graph API helpers (host
graph.instagram.com). No Telegram coupling, no vault reads — caller
hands us the token + ig_account_id and we run the flow.

Endpoints verified against
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing
at build time:

  Create child:   POST /{API}/{ig_id}/media   (image_url, is_carousel_item=true)
  Create parent:  POST /{API}/{ig_id}/media   (media_type=CAROUSEL, children=ID,ID,...,
                                               caption)
  Poll status:    GET  /{API}/{container_id}?fields=status_code
                  values: FINISHED | IN_PROGRESS | ERROR | EXPIRED | PUBLISHED
  Publish:        POST /{API}/{ig_id}/media_publish   (creation_id)
  Permalink:      GET  /{API}/{media_id}?fields=permalink

Limits we enforce / are aware of:
  - Carousel: 10 children max (we clamp; renderer typically yields ≤8).
  - JPEG only (the staging layer handles conversion).
  - All slides crop to the first slide's aspect (caller's responsibility).
  - Caption ~2200 chars max — we trim with an ellipsis if longer.

Tokens are NEVER logged. On non-200 we log status + a body excerpt and
raise PublishError, with auth_failed=True for 401-class so the caller
can clear the token and prompt reconnection."""

import asyncio
import logging

import aiohttp

logger = logging.getLogger(__name__)

GRAPH_VERSION = "v23.0"
GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_VERSION}"

CAROUSEL_MAX_CHILDREN = 10
CAPTION_MAX_CHARS = 2200

POLL_INTERVAL_SECONDS = 4
POLL_TIMEOUT_SECONDS = 120


class PublishError(RuntimeError):
    """Non-200 from a publish endpoint, container ERROR/EXPIRED, or timeout."""

    def __init__(self, message: str, *, auth_failed: bool = False) -> None:
        super().__init__(message)
        self.auth_failed = auth_failed


def _truncate_caption(text: str) -> str:
    if len(text) <= CAPTION_MAX_CHARS:
        return text
    return text[: CAPTION_MAX_CHARS - 1].rstrip() + "…"


async def _post(session: aiohttp.ClientSession, url: str, data: dict) -> dict:
    async with session.post(url, data=data) as resp:
        body = await resp.text()
        if resp.status != 200:
            logger.warning("IG publish POST %s -> %d body=%r", url, resp.status, body[:300])
            raise PublishError(
                f"POST {url} returned {resp.status}",
                auth_failed=resp.status in (401, 403),
            )
        try:
            return await resp.json(content_type=None)
        except aiohttp.ContentTypeError as e:
            raise PublishError(f"POST {url} non-JSON body: {body[:200]}") from e


async def _get(session: aiohttp.ClientSession, url: str, params: dict) -> dict:
    async with session.get(url, params=params) as resp:
        body = await resp.text()
        if resp.status != 200:
            logger.warning("IG publish GET %s -> %d body=%r", url, resp.status, body[:300])
            raise PublishError(
                f"GET {url} returned {resp.status}",
                auth_failed=resp.status in (401, 403),
            )
        try:
            return await resp.json(content_type=None)
        except aiohttp.ContentTypeError as e:
            raise PublishError(f"GET {url} non-JSON body: {body[:200]}") from e


async def create_child_container(
    session: aiohttp.ClientSession,
    ig_id: str,
    image_url: str,
    token: str,
) -> str:
    """Create a child container for one carousel slide. Returns its creation id."""
    payload = await _post(session, f"{GRAPH_BASE}/{ig_id}/media", {
        "image_url": image_url,
        "is_carousel_item": "true",
        "access_token": token,
    })
    cid = payload.get("id")
    if not cid:
        raise PublishError(f"child container response missing id: keys={list(payload)}")
    return str(cid)


async def create_carousel_container(
    session: aiohttp.ClientSession,
    ig_id: str,
    child_ids: list[str],
    caption: str,
    token: str,
) -> str:
    """Create the parent carousel container. Returns the parent creation id."""
    if not child_ids:
        raise PublishError("create_carousel_container: no child_ids")
    payload = await _post(session, f"{GRAPH_BASE}/{ig_id}/media", {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": _truncate_caption(caption),
        "access_token": token,
    })
    cid = payload.get("id")
    if not cid:
        raise PublishError(f"parent container response missing id: keys={list(payload)}")
    return str(cid)


async def wait_until_finished(
    session: aiohttp.ClientSession,
    container_id: str,
    token: str,
    timeout_s: int = POLL_TIMEOUT_SECONDS,
) -> None:
    """Poll status_code until FINISHED or PUBLISHED. Raise on ERROR/EXPIRED
    or timeout. For pure-image carousels this is usually instant."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        payload = await _get(session, f"{GRAPH_BASE}/{container_id}", {
            "fields": "status_code",
            "access_token": token,
        })
        status = payload.get("status_code")
        if status in ("FINISHED", "PUBLISHED"):
            return
        if status in ("ERROR", "EXPIRED"):
            raise PublishError(f"container {container_id} status={status}")
        if asyncio.get_event_loop().time() > deadline:
            raise PublishError(f"container {container_id} still {status} after {timeout_s}s")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def publish_container(
    session: aiohttp.ClientSession,
    ig_id: str,
    creation_id: str,
    token: str,
) -> str:
    """Publish the parent container. Returns the published media id."""
    payload = await _post(session, f"{GRAPH_BASE}/{ig_id}/media_publish", {
        "creation_id": creation_id,
        "access_token": token,
    })
    mid = payload.get("id")
    if not mid:
        raise PublishError(f"media_publish response missing id: keys={list(payload)}")
    return str(mid)


async def get_permalink(
    session: aiohttp.ClientSession,
    media_id: str,
    token: str,
) -> str | None:
    """Best-effort permalink fetch. Returns None on failure so the caller
    can still report a successful publish."""
    try:
        payload = await _get(session, f"{GRAPH_BASE}/{media_id}", {
            "fields": "permalink",
            "access_token": token,
        })
    except PublishError as e:
        logger.warning("permalink fetch failed for media_id=%s: %s", media_id, e)
        return None
    link = payload.get("permalink")
    return str(link) if link else None


async def publish_carousel(
    ig_id: str,
    image_urls: list[str],
    caption: str,
    token: str,
) -> dict:
    """End-to-end: child containers → parent container → wait → publish →
    permalink. Returns {media_id, permalink}. Clamps to the 10-child max.

    The token is passed in by the caller; we never log it. On 401-class
    failures PublishError.auth_failed is True so the caller can clear the
    stored token and prompt the user to reconnect."""
    if not image_urls:
        raise PublishError("publish_carousel: no image_urls")
    if not ig_id:
        raise PublishError("publish_carousel: empty ig_id")

    children_urls = image_urls[:CAROUSEL_MAX_CHILDREN]
    if len(image_urls) > CAROUSEL_MAX_CHILDREN:
        logger.warning(
            "Carousel had %d slides, clamping to %d",
            len(image_urls), CAROUSEL_MAX_CHILDREN,
        )

    async with aiohttp.ClientSession() as session:
        child_ids: list[str] = []
        for url in children_urls:
            cid = await create_child_container(session, ig_id, url, token)
            child_ids.append(cid)
        logger.info("Created %d child container(s) for ig_id=%s", len(child_ids), ig_id)

        parent_id = await create_carousel_container(
            session, ig_id, child_ids, caption, token,
        )
        logger.info("Created parent carousel container parent_id=%s", parent_id)

        await wait_until_finished(session, parent_id, token)

        media_id = await publish_container(session, ig_id, parent_id, token)
        logger.info("Published media_id=%s for ig_id=%s", media_id, ig_id)

        permalink = await get_permalink(session, media_id, token)

    return {"media_id": media_id, "permalink": permalink}

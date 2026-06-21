"""Facebook Page carousel publish — pure Graph API helpers (host
graph.facebook.com). Mirrors instagram/publish.py: no Telegram coupling,
no vault reads — the caller hands us the Page token + Page id.

Multi-photo Page post flow:
  1. For each slide url: POST /{API}/{page_id}/photos
     {url, published="false", access_token} -> {id}   (unpublished photo)
  2. POST /{API}/{page_id}/feed
     {message, attached_media=<json list of {media_fbid}>, access_token}
     -> {id: "<page>_<post>"}
  3. Permalink: https://www.facebook.com/<post_id>

published="false" on the photos step is CRITICAL: it keeps each slide from
posting as its own photo, so they attach to ONE feed post instead.

Tokens are NEVER logged. On non-200 we log status + a body excerpt and
raise FacebookPublishError, with auth_failed=True for 401/403 so the
caller can clear the token and prompt reconnection."""

import json
import logging

import aiohttp

logger = logging.getLogger(__name__)

GRAPH_VERSION = "v23.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

PHOTOS_MAX = 10  # match the carousel renderer's ceiling
CAPTION_MAX_CHARS = 5000  # FB allows long captions; trim defensively


class FacebookPublishError(RuntimeError):
    """Non-200 from a publish endpoint."""

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
            logger.warning("FB publish POST %s -> %d body=%r", url, resp.status, body[:300])
            raise FacebookPublishError(
                f"POST {url} returned {resp.status}",
                auth_failed=resp.status in (401, 403),
            )
        try:
            return await resp.json(content_type=None)
        except aiohttp.ContentTypeError as e:
            raise FacebookPublishError(f"POST {url} non-JSON body: {body[:200]}") from e


async def upload_unpublished_photo(
    session: aiohttp.ClientSession,
    page_id: str,
    image_url: str,
    page_token: str,
) -> str:
    """Upload one slide as an UNPUBLISHED photo. Returns its fbid."""
    payload = await _post(session, f"{GRAPH_BASE}/{page_id}/photos", {
        "url": image_url,
        "published": "false",
        "access_token": page_token,
    })
    pid = payload.get("id")
    if not pid:
        raise FacebookPublishError(f"photo response missing id: keys={list(payload)}")
    return str(pid)


async def create_feed_post(
    session: aiohttp.ClientSession,
    page_id: str,
    photo_ids: list[str],
    caption: str,
    page_token: str,
) -> str:
    """Create the feed post that attaches all uploaded photos. Returns the
    post id ("<page>_<post>")."""
    if not photo_ids:
        raise FacebookPublishError("create_feed_post: no photo_ids")
    attached_media = json.dumps([{"media_fbid": pid} for pid in photo_ids])
    payload = await _post(session, f"{GRAPH_BASE}/{page_id}/feed", {
        "message": _truncate_caption(caption),
        "attached_media": attached_media,
        "access_token": page_token,
    })
    post_id = payload.get("id")
    if not post_id:
        raise FacebookPublishError(f"feed response missing id: keys={list(payload)}")
    return str(post_id)


async def publish_facebook_carousel(
    page_id: str,
    image_urls: list[str],
    caption: str,
    page_token: str,
) -> dict:
    """End-to-end: upload each slide unpublished -> one feed post attaching
    them all. Returns {post_id, permalink}. Clamps to PHOTOS_MAX.

    On 401/403 FacebookPublishError.auth_failed is True so the caller can
    clear the stored token and prompt reconnection."""
    if not image_urls:
        raise FacebookPublishError("publish_facebook_carousel: no image_urls")
    if not page_id:
        raise FacebookPublishError("publish_facebook_carousel: empty page_id")

    urls = image_urls[:PHOTOS_MAX]
    if len(image_urls) > PHOTOS_MAX:
        logger.warning(
            "FB post had %d slides, clamping to %d", len(image_urls), PHOTOS_MAX,
        )

    async with aiohttp.ClientSession() as session:
        photo_ids: list[str] = []
        for url in urls:
            pid = await upload_unpublished_photo(session, page_id, url, page_token)
            photo_ids.append(pid)
        logger.info("Uploaded %d unpublished photo(s) for page_id=%s", len(photo_ids), page_id)

        post_id = await create_feed_post(session, page_id, photo_ids, caption, page_token)
        logger.info("Created FB feed post post_id=%s for page_id=%s", post_id, page_id)

    permalink = f"https://www.facebook.com/{post_id}"
    return {"post_id": post_id, "permalink": permalink}

"""aiohttp app that handles the public Instagram OAuth callback.

Runs in-process alongside the Telegram bot on the same event loop, bound
to localhost on OAUTH_CALLBACK_PORT. Caddy reverse-proxies the public
HTTPS URL to it.

Flow on GET /oauth/callback:
  1. Read `code` and `state` from query string.
  2. consume_state(state) -> user_id or None.
     Anything that doesn't validate gets a 400 'invalid or expired' page
     and we do NOT do any token exchange. This is what makes the public
     endpoint safe with multi-user.
  3. exchange code -> short token -> long token -> ig_account_id.
  4. save_token(user_id, ...). Render a success page.

We never log the access token or the app secret. On failure we render a
generic error page and log a short note (status / error message only)."""

import logging

from aiohttp import web

from ai_social_content_generator.instagram.oauth import (
    OAuthError,
    exchange_code_for_short_token,
    exchange_short_for_long,
    get_ig_account_id,
)
from ai_social_content_generator.instagram.oauth_state import consume_state
from ai_social_content_generator.instagram.token_store import save_token
from ai_social_content_generator.facebook.oauth import (
    FacebookOAuthError,
    exchange_code_for_user_token,
    exchange_for_long_user_token,
    get_pages,
)
from ai_social_content_generator.facebook.token_store import save_fb_token

logger = logging.getLogger(__name__)


def _page(title: str, body: str, status: int = 200) -> web.Response:
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 480px;
          margin: 80px auto; padding: 0 24px; color: #1a1a1a; line-height: 1.5; }}
  h1 {{ font-size: 24px; margin-bottom: 12px; }}
  p {{ color: #555; }}
</style>
</head><body><h1>{title}</h1>{body}</body></html>"""
    return web.Response(text=html, status=status, content_type="text/html")


def _success_page() -> web.Response:
    return _page(
        "Instagram connected ✓",
        "<p>You can close this tab and return to Telegram.</p>",
    )


def _invalid_page() -> web.Response:
    return _page(
        "Link invalid or expired",
        "<p>Open Telegram and tap <b>Connect Instagram</b> again to start fresh.</p>",
        status=400,
    )


def _error_page() -> web.Response:
    return _page(
        "Couldn't connect Instagram",
        "<p>Something went wrong on our side. Try again from Telegram, "
        "or contact support if it keeps failing.</p>",
        status=500,
    )


async def _handle_callback(request: web.Request) -> web.Response:
    code = request.query.get("code", "")
    state = request.query.get("state", "")
    error = request.query.get("error", "")

    if error:
        # User denied or Instagram rejected — `state` is consumed so they
        # can't replay; render an invalid page either way.
        consume_state(state)
        logger.info("OAuth callback returned error=%s", error)
        return _invalid_page()

    user_id = consume_state(state)
    if user_id is None:
        logger.warning("OAuth callback with invalid/expired state")
        return _invalid_page()

    if not code:
        logger.warning("OAuth callback for user_id=%s missing code", user_id)
        return _invalid_page()

    try:
        short = await exchange_code_for_short_token(code)
        long_payload = await exchange_short_for_long(short["access_token"])
        ig_id = await get_ig_account_id(long_payload["access_token"])
        save_token(
            user_id=user_id,
            token=long_payload["access_token"],
            expires_in=int(long_payload["expires_in"]),
            ig_account_id=ig_id,
        )
    except OAuthError as e:
        logger.warning("OAuth exchange failed for user_id=%s: %s", user_id, e)
        return _error_page()
    except Exception:
        logger.exception("Unexpected OAuth callback error for user_id=%s", user_id)
        return _error_page()

    return _success_page()


def _fb_success_page(page_name: str, multiple: bool) -> web.Response:
    note = (
        f"<p>Connected Page: <b>{page_name}</b>.</p>"
        if page_name else "<p>Your Page is connected.</p>"
    )
    if multiple:
        note += (
            "<p>You manage more than one Page. If this is the wrong one, "
            "reconnect from Telegram to switch.</p>"
        )
    return _page("Facebook connected ✓", note + "<p>You can close this tab.</p>")


def _fb_no_page_page() -> web.Response:
    return _page(
        "No Facebook Page found",
        "<p>This account doesn't admin a Page the app can post to. Create a "
        "Page (or get admin access), then reconnect from Telegram.</p>",
        status=400,
    )


async def _handle_fb_callback(request: web.Request) -> web.Response:
    code = request.query.get("code", "")
    state = request.query.get("state", "")
    error = request.query.get("error", "")

    if error:
        consume_state(state)
        logger.info("FB OAuth callback returned error=%s", error)
        return _invalid_page()

    user_id = consume_state(state)
    if user_id is None:
        logger.warning("FB OAuth callback with invalid/expired state")
        return _invalid_page()

    if not code:
        logger.warning("FB OAuth callback for user_id=%s missing code", user_id)
        return _invalid_page()

    try:
        user_tok = await exchange_code_for_user_token(code)
        long_payload = await exchange_for_long_user_token(user_tok["access_token"])
        pages = await get_pages(long_payload["access_token"])
        if not pages:
            logger.warning("FB OAuth: no Pages for user_id=%s", user_id)
            return _fb_no_page_page()
        # v1: use the first Page; surface its name so the user can confirm
        # (and reconnect to switch if they admin several).
        page = pages[0]
        save_fb_token(
            user_id=user_id,
            page_token=page["access_token"],
            page_id=page["id"],
            page_name=page.get("name", ""),
        )
    except FacebookOAuthError as e:
        logger.warning("FB OAuth exchange failed for user_id=%s: %s", user_id, e)
        return _error_page()
    except Exception:
        logger.exception("Unexpected FB OAuth callback error for user_id=%s", user_id)
        return _error_page()

    return _fb_success_page(page.get("name", ""), multiple=len(pages) > 1)


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/oauth/callback", _handle_callback)
    app.router.add_get("/oauth/facebook/callback", _handle_fb_callback)
    return app


async def start_callback_server(port: int) -> web.AppRunner:
    """Start the aiohttp app on the current event loop, bound to localhost
    on the given port. Returns the runner so the caller can keep it alive
    (and shut it down if needed). Caddy reverse-proxies the public
    https://img.sean.build/oauth/callback to this."""
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    logger.info("OAuth callback server listening on 127.0.0.1:%d", port)
    return runner

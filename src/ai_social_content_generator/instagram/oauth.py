"""Instagram OAuth — pure HTTP helpers for the Instagram API with Instagram
Login flow (host graph.instagram.com). No Telegram coupling.

Endpoints verified against
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login
at build time:
  Authorize:  GET  https://www.instagram.com/oauth/authorize
  Code→short: POST https://api.instagram.com/oauth/access_token
  Short→long: GET  https://graph.instagram.com/access_token
  Refresh:    GET  https://graph.instagram.com/refresh_access_token
  IG user id: GET  https://graph.instagram.com/me?fields=user_id

App secret is used ONLY in server-side exchanges. NEVER log or return the
secret or any access token to the client. On non-200 responses we log the
status + body excerpt at WARNING and raise OAuthError.
"""

import logging
import os
from urllib.parse import urlencode
from dotenv import load_dotenv, find_dotenv
import aiohttp

logger = logging.getLogger(__name__)
load_dotenv(find_dotenv())

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_EXCHANGE_URL = "https://api.instagram.com/oauth/access_token"
LONG_TOKEN_URL = "https://graph.instagram.com/access_token"
REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
ME_URL = "https://graph.instagram.com/me"

SCOPES = "instagram_business_basic,instagram_business_content_publish"


class OAuthError(RuntimeError):
    """Non-200 from a Meta OAuth endpoint, or missing required env."""


def _app_id() -> str:
    v = os.getenv("INSTAGRAM_APP_ID")
    if not v:
        raise OAuthError("INSTAGRAM_APP_ID not set")
    return v


def _app_secret() -> str:
    v = os.getenv("INSTAGRAM_APP_SECRET")
    if not v:
        raise OAuthError("INSTAGRAM_APP_SECRET not set")
    return v


def _redirect_uri() -> str:
    v = os.getenv("INSTAGRAM_REDIRECT_URI")
    if not v:
        raise OAuthError("INSTAGRAM_REDIRECT_URI not set")
    return v


def build_authorize_url(state: str) -> str:
    """The URL the user is sent to in their browser to approve the app."""
    params = {
        "client_id": _app_id(),
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def _post_form(url: str, data: dict) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data) as resp:
            body = await resp.text()
            if resp.status != 200:
                logger.warning(
                    "Instagram OAuth POST %s -> %d body=%r", url, resp.status, body[:300],
                )
                raise OAuthError(f"POST {url} returned {resp.status}")
            try:
                return await resp.json(content_type=None)
            except aiohttp.ContentTypeError:
                raise OAuthError(f"POST {url} returned non-JSON body: {body[:200]}")


async def _get_json(url: str, params: dict) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            body = await resp.text()
            if resp.status != 200:
                logger.warning(
                    "Instagram OAuth GET %s -> %d body=%r", url, resp.status, body[:300],
                )
                raise OAuthError(f"GET {url} returned {resp.status}")
            try:
                return await resp.json(content_type=None)
            except aiohttp.ContentTypeError:
                raise OAuthError(f"GET {url} returned non-JSON body: {body[:200]}")


async def exchange_code_for_short_token(code: str) -> dict:
    """Trade the one-time `code` from the redirect for a short-lived
    (~1 hour) access token. Returns the raw payload, expected keys:
    access_token, user_id."""
    payload = await _post_form(TOKEN_EXCHANGE_URL, {
        "client_id": _app_id(),
        "client_secret": _app_secret(),
        "grant_type": "authorization_code",
        "redirect_uri": _redirect_uri(),
        "code": code,
    })
    if "access_token" not in payload:
        raise OAuthError(f"code exchange missing access_token: keys={list(payload)}")
    return payload


async def exchange_short_for_long(short_token: str) -> dict:
    """Trade a short-lived token for a long-lived (~60 day) token.
    Returns: access_token, token_type, expires_in (seconds)."""
    payload = await _get_json(LONG_TOKEN_URL, {
        "grant_type": "ig_exchange_token",
        "client_secret": _app_secret(),
        "access_token": short_token,
    })
    if "access_token" not in payload or "expires_in" not in payload:
        raise OAuthError(f"long-token exchange missing fields: keys={list(payload)}")
    return payload


async def refresh_long_token(long_token: str) -> dict:
    """Refresh a long-lived token (must be ≥24h old). Returns the same
    shape as exchange_short_for_long: access_token, token_type, expires_in."""
    payload = await _get_json(REFRESH_URL, {
        "grant_type": "ig_refresh_token",
        "access_token": long_token,
    })
    if "access_token" not in payload or "expires_in" not in payload:
        raise OAuthError(f"refresh missing fields: keys={list(payload)}")
    return payload


async def get_ig_account_id(token: str) -> str:
    """Return the IG-scoped user_id for the account this token belongs to.
    This is what later phases pass to the Graph API for publishing."""
    payload = await _get_json(ME_URL, {
        "fields": "user_id",
        "access_token": token,
    })
    user_id = payload.get("user_id") or payload.get("id")
    if not user_id:
        raise OAuthError(f"/me missing user_id: keys={list(payload)}")
    return str(user_id)

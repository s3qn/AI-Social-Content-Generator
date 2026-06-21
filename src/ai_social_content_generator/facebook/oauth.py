"""Facebook OAuth — pure HTTP helpers for the Facebook Login flow (host
graph.facebook.com, NOT graph.instagram.com). Mirrors instagram/oauth.py.

Flow:
  Authorize:        GET  https://www.facebook.com/v23.0/dialog/oauth
  Code -> user tok: GET  https://graph.facebook.com/v23.0/oauth/access_token
  Long user token:  GET  https://graph.facebook.com/v23.0/oauth/access_token
                         ?grant_type=fb_exchange_token&fb_exchange_token=<short>
  Pages:            GET  https://graph.facebook.com/v23.0/me/accounts
                         -> data[].{id, name, access_token}

The Page access_token derived from a LONG-LIVED user token never expires,
so there is no refresh job (unlike Instagram).

App secret is used ONLY in server-side exchanges. NEVER log the secret or
any access token. On non-200 we log status + body excerpt and raise
FacebookOAuthError.
"""

import logging
import os
from urllib.parse import urlencode

import aiohttp
from dotenv import find_dotenv, load_dotenv

logger = logging.getLogger(__name__)
load_dotenv(find_dotenv())

GRAPH_VERSION = "v23.0"
AUTHORIZE_URL = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
TOKEN_URL = f"https://graph.facebook.com/{GRAPH_VERSION}/oauth/access_token"
ACCOUNTS_URL = f"https://graph.facebook.com/{GRAPH_VERSION}/me/accounts"

SCOPES = "pages_manage_posts,pages_read_engagement,pages_show_list"


class FacebookOAuthError(RuntimeError):
    """Non-200 from a Facebook OAuth endpoint, or missing required env."""


def _app_id() -> str:
    v = os.getenv("FACEBOOK_APP_ID")
    if not v:
        raise FacebookOAuthError("FACEBOOK_APP_ID not set")
    return v


def _app_secret() -> str:
    v = os.getenv("FACEBOOK_APP_SECRET")
    if not v:
        raise FacebookOAuthError("FACEBOOK_APP_SECRET not set")
    return v


def _redirect_uri() -> str:
    v = os.getenv("FACEBOOK_REDIRECT_URI")
    if not v:
        raise FacebookOAuthError("FACEBOOK_REDIRECT_URI not set")
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


async def _get_json(url: str, params: dict) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            body = await resp.text()
            if resp.status != 200:
                logger.warning(
                    "Facebook OAuth GET %s -> %d body=%r", url, resp.status, body[:300],
                )
                raise FacebookOAuthError(f"GET {url} returned {resp.status}")
            try:
                return await resp.json(content_type=None)
            except aiohttp.ContentTypeError as e:
                raise FacebookOAuthError(
                    f"GET {url} returned non-JSON body: {body[:200]}"
                ) from e


async def exchange_code_for_user_token(code: str) -> dict:
    """Trade the one-time `code` from the redirect for a (short-lived) user
    access token. Returns the raw payload (expected key: access_token)."""
    payload = await _get_json(TOKEN_URL, {
        "client_id": _app_id(),
        "client_secret": _app_secret(),
        "redirect_uri": _redirect_uri(),
        "code": code,
    })
    if "access_token" not in payload:
        raise FacebookOAuthError(
            f"code exchange missing access_token: keys={list(payload)}"
        )
    return payload


async def exchange_for_long_user_token(short_user_token: str) -> dict:
    """Trade a short-lived user token for a long-lived one. Page tokens
    derived from this never expire. Returns payload with access_token."""
    payload = await _get_json(TOKEN_URL, {
        "grant_type": "fb_exchange_token",
        "client_id": _app_id(),
        "client_secret": _app_secret(),
        "fb_exchange_token": short_user_token,
    })
    if "access_token" not in payload:
        raise FacebookOAuthError(
            f"long-token exchange missing access_token: keys={list(payload)}"
        )
    return payload


async def get_pages(long_user_token: str) -> list[dict]:
    """Return the Pages this user administers, each as
    {id, name, access_token}. The access_token here is the never-expiring
    Page token used to publish."""
    payload = await _get_json(ACCOUNTS_URL, {
        "access_token": long_user_token,
        "fields": "id,name,access_token",
    })
    data = payload.get("data")
    if not isinstance(data, list):
        raise FacebookOAuthError(f"/me/accounts missing data: keys={list(payload)}")
    pages: list[dict] = []
    for p in data:
        if p.get("id") and p.get("access_token"):
            pages.append({
                "id": str(p["id"]),
                "name": p.get("name", ""),
                "access_token": p["access_token"],
            })
    return pages

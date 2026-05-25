from apify_client import ApifyClient
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import os
import json
import argparse
import re


VIRAL_ACTOR_ID = "patient_discovery/instagram-search-reels"
VIRAL_PAGES_PER_KEYWORD = 2
VIRAL_RECENT_DAYS = 30
VIRAL_TOP_EVER = 3
VIRAL_TOP_RECENT = 2


def load_apify_api_key():

    load_dotenv(find_dotenv())
    apify_api_key = os.getenv("APIFY_API_KEY")
    return apify_api_key

def convert_to_json(data, handle, suffix):

    with open(Path(__file__).resolve().parents[3] / "cache" / f"{handle}-{suffix}.json", "w") as f:
        json.dump(data, f, indent=2, default=str)
    return None

def fetch_posts(apify_api_key, handle, limit=20):

    client = ApifyClient(apify_api_key)
    actor_client = client.actor('apify/instagram-scraper')
    result = actor_client.call(run_input={
        "directUrls": [f"https://www.instagram.com/{handle}/"],
        "resultsType": "posts",
        "resultsLimit": limit,
    })

    if result is None:
        print('Actor run failed...')
        return

    data = client.dataset(result["defaultDatasetId"])
    data_list = data.list_items().items
    return data_list

def fetch_profile(apify_api_key, handle):

    client = ApifyClient(apify_api_key)
    actor_client = client.actor('apify/instagram-scraper')
    result = actor_client.call(run_input={
        "directUrls": [f"https://www.instagram.com/{handle}/"],
        "resultsType": "details",
        "resultsLimit": 1,
    })

    if result is None:
        print('Actor run failed...')
        return

    # FOR DEBUG: print(f"Result keys: {result.keys()}")

    data = client.dataset(result["defaultDatasetId"])
    data_list = data.list_items().items
    return data_list

def get_profile(user, limit):

    cache_dir = Path(__file__).resolve().parents[3] / "cache"
    profile_path = cache_dir / f"{user}-profile.json"
    
    if profile_path.exists():
        print(f"Found cache on disk for @{user}, skipping scrape")
        profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
        return profile_data[0]
    
    print("Cache not found... proceeding to scrape")
    # Load API Key

    print("Loading API Key...")
    apify_api_key = load_apify_api_key()

    # Scrape handle from the gram

    print(f"Scraping for @{user}")
    print(f"Scraping {limit} posts for @{user}...")
    post_data = fetch_posts(apify_api_key, user, limit)

    print(f"Scraping profile for @{user}...")
    profile_data = fetch_profile(apify_api_key, user)
    
    print("Saving to cache...")
    convert_to_json(post_data, user, "posts")
    convert_to_json(profile_data, user, "profile")

    print(f"Done! Saved {len(post_data)} posts and profile for @{user}!")
    return profile_data[0]

def _sanitize_keyword_for_filename(keyword: str) -> str:
    """Make a keyword safe for use as a filename. Replace whitespace,
    quotes, slashes, and other unsafe chars with underscores. Hebrew
    and other Unicode letters are kept as-is (Linux fs supports them)."""
    safe = re.sub(r'[\s/\\\'"<>:|?*]+', '_', keyword)
    return safe[:80]


def viral_cache_path(keyword: str) -> Path:
    safe = _sanitize_keyword_for_filename(keyword)
    return Path(__file__).resolve().parents[3] / "cache" / f"viral_{safe}.json"


def fetch_viral_reels(apify_api_key: str, keyword: str) -> list[dict]:
    """Call patient_discovery/instagram-search-reels Actor for one
    keyword. Returns raw post list (no dedup, no filter, no rank)."""
    client = ApifyClient(apify_api_key)
    actor_client = client.actor(VIRAL_ACTOR_ID)
    result = actor_client.call(run_input={
        "search": keyword,
        "maxPages": VIRAL_PAGES_PER_KEYWORD,
    })

    if result is None:
        print(f"Viral actor run failed for keyword={keyword!r}")
        return []

    data = client.dataset(result["defaultDatasetId"])
    return data.list_items().items


def get_viral_reels(keyword: str, force_refresh: bool = False) -> list[dict]:
    """Public entry. Cache-first (mirrors get_profile). Returns raw post
    list. force_refresh=True bypasses cache."""
    cache_path = viral_cache_path(keyword)

    if cache_path.exists() and not force_refresh:
        print(f"Found viral cache on disk for keyword={keyword!r}, skipping scrape")
        return json.loads(cache_path.read_text(encoding="utf-8"))

    print(f"Viral cache not found for keyword={keyword!r}, scraping...")
    apify_api_key = load_apify_api_key()
    raw = fetch_viral_reels(apify_api_key, keyword)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(raw, f, indent=2, default=str)

    print(f"Saved {len(raw)} viral reels for keyword={keyword!r}")
    return raw


def dedup_viral_posts(posts: list[dict]) -> list[dict]:
    """Dedup by `code`. Keep first occurrence."""
    seen: set[str] = set()
    out: list[dict] = []
    for p in posts:
        code = p.get("code")
        if code and code not in seen:
            seen.add(code)
            out.append(p)
    return out


def compute_viral_engagement_score(post: dict) -> float:
    """(shares + comments) / views. Returns 0 if views missing/zero."""
    views = post.get("ig_play_count") or post.get("play_count") or 0
    if views <= 0:
        return 0.0
    shares = post.get("share_count") or 0
    comments = post.get("comment_count") or 0
    return (shares + comments) / views


def is_recent_viral_post(post: dict, days: int = VIRAL_RECENT_DAYS) -> bool:
    """True if post.taken_at (Unix ts) is within the last N days."""
    taken_at = post.get("taken_at")
    if not taken_at:
        return False
    try:
        post_date = datetime.fromtimestamp(taken_at, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return post_date >= cutoff


def tier_and_rank_viral(posts: list[dict]) -> list[dict]:
    """Top 3 by score (all-time) + top 2 by score (last 30 days), no
    overlap between tiers. Tags each post with `_viral_tier`."""
    if not posts:
        return []

    sorted_all = sorted(posts, key=compute_viral_engagement_score, reverse=True)
    top_ever = sorted_all[:VIRAL_TOP_EVER]
    top_ever_codes = {p.get("code") for p in top_ever}

    remaining_recent = [
        p for p in sorted_all
        if p.get("code") not in top_ever_codes and is_recent_viral_post(p)
    ]
    top_recent = remaining_recent[:VIRAL_TOP_RECENT]

    for p in top_ever:
        p["_viral_tier"] = "ever"
    for p in top_recent:
        p["_viral_tier"] = "recent"

    return top_ever + top_recent


def extract_viral_summary(post: dict, keyword: str) -> dict:
    """Pull flat fields for display + future Excel export."""
    caption_text = ""
    caption_obj = post.get("caption")
    if isinstance(caption_obj, dict):
        caption_text = caption_obj.get("text", "") or ""
    elif isinstance(caption_obj, str):
        caption_text = caption_obj

    user_obj = post.get("user") or {}
    username = user_obj.get("username", "unknown")

    code = post.get("code", "")
    post_url = f"https://www.instagram.com/reel/{code}/" if code else ""

    taken_at = post.get("taken_at")
    if taken_at:
        try:
            post_date = datetime.fromtimestamp(taken_at, tz=timezone.utc).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            post_date = "unknown"
    else:
        post_date = "unknown"

    return {
        "caption": caption_text,
        "likes": post.get("like_count") or 0,
        "comments": post.get("comment_count") or 0,
        "views": post.get("ig_play_count") or post.get("play_count") or 0,
        "shares": post.get("share_count") or 0,
        "username": username,
        "post_url": post_url,
        "post_date": post_date,
        "keyword_source": keyword,
        "engagement_score": compute_viral_engagement_score(post),
        "tier": post.get("_viral_tier", "ever"),
    }


def scrape_and_process_viral_keywords(
    keywords: list[str],
    force_refresh: bool = False,
) -> list[dict]:
    """Full pipeline for multiple keywords. Returns flat list of summary
    dicts (up to 5 per keyword)."""
    all_results: list[dict] = []
    for kw in keywords:
        raw = get_viral_reels(kw, force_refresh=force_refresh)
        deduped = dedup_viral_posts(raw)
        tiered = tier_and_rank_viral(deduped)
        for post in tiered:
            all_results.append(extract_viral_summary(post, kw))
        print(f"keyword={kw!r}: {len(raw)} raw → {len(deduped)} deduped → {len(tiered)} kept")
    return all_results


def invalidate_viral_cache(keyword: str | None = None) -> int:
    """Delete cached viral results. If keyword is None, delete all
    viral_*.json. Returns count of files deleted."""
    cache_dir = Path(__file__).resolve().parents[3] / "cache"
    if not cache_dir.exists():
        return 0

    if keyword is not None:
        path = viral_cache_path(keyword)
        if path.exists():
            path.unlink()
            return 1
        return 0

    count = 0
    for p in cache_dir.glob("viral_*.json"):
        p.unlink()
        count += 1
    return count


def main():

    parser = argparse.ArgumentParser(description="Fetch instagram posts from handle")
    parser.add_argument("--user", help="Instagram Handle to fetch (e.g: nasa)" ,default="inna_cheskis")
    parser.add_argument("-p" ,"--post-number", choices=range(1, 21), type=int, help="How many posts to fetch from profile (1-20)", default=1)
    args = parser.parse_args()
    user = args.user
    limit = args.post_number

    # Scrape Content
    get_profile(user, limit)

if __name__ == "__main__":
    main()
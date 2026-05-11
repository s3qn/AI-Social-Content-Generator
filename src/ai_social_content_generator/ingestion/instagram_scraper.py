from apify_client import ApifyClient
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
import os
import json
import argparse


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

def main():
    
    parser = argparse.ArgumentParser(description="Fetch instagram posts from handle")
    parser.add_argument("--user", help="Instagram Handle to fetch (e.g: nasa)" ,default="inna_cheskis")
    parser.add_argument("-p" ,"--post-number", choices=range(1, 21), type=int, help="How many posts to fetch from profile (1-20)", default=1)
    args = parser.parse_args()
    user = args.user
    limit = args.post_number

    # Scrape Content
    scrape_to_cache(user, limit)

if __name__ == "__main__":
    main()
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

def convert_to_json(data, handle):

    with open(Path(__file__).resolve().parents[3] / "cache" / f"{handle}-posts.json", "w") as f:
        json.dump(data, f, indent=2, default=str)
    return None

def fetch_handle(apify_api_key, handle):

    client = ApifyClient(apify_api_key)
    actor_client = client.actor('apify/instagram-scraper')
    result = actor_client.call(run_input={
        "directUrls": [f"https://www.instagram.com/{handle}/"],
        "resultsType": "posts",
        "resultsLimit": 1,
    })

    if result is None:
        print('Actor run failed...')
        return

    # FOR DEBUG: print(f"Result keys: {result.keys()}")

    data = client.dataset(result["defaultDatasetId"])
    data_list = data.list_items().items
    return data_list

def main():
    
    parser = argparse.ArgumentParser(description="Fetch instagram posts from handle")
    parser.add_argument("--user", help="Instagram Handle to fetch (e.g: nasa)" ,default="inna_cheskis")
    args = parser.parse_args()
    user = args.user

    # Load API Key
    apify_api_key = load_apify_api_key()
    
    # Scrape handle from the gram
    data = fetch_handle(apify_api_key, user)
    convert_to_json(data, user)

    print(f'Dataset: {data}')

if __name__ == "__main__":
    main()
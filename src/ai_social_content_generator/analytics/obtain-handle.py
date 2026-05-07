from apify_client import ApifyClient
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
import os
import json


load_dotenv(Path("/home/sean/ai-projects/AI-Social-Content-Generator/.env"))
apify_api_key = os.getenv("APIFY_API_KEY")

def convert_to_json(data):
    with open(Path("/home/sean/ai-projects/AI-Social-Content-Generator/cache/test.json"), "w") as f:
        json.dump(data, f, indent=2, default=str)
    return None

def main():
    
    client = ApifyClient(apify_api_key)
    actor_client = client.actor('apify/instagram-scraper')
    result = actor_client.call(run_input={
        "directUrls": ["https://www.instagram.com/inna_cheskis/"],
        "resultsType": "posts",
        "resultsLimit": 1,                       
    })

    if result is None:
        print('Actor run failed...')
        return
    
    print(f"Result keys: {result.keys()}")

    data = client.dataset(result["defaultDatasetId"])
    data_list = data.list_items().items
    data_json = convert_to_json(data_list)





    print(f'Dataset: {data_json}')





if __name__ == "__main__":
    main()
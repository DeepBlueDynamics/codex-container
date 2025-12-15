#!/usr/bin/env python3
"""
Quick SerpAPI Google Images fetcher.

Usage:
  SERPAPI_API_KEY=... python3 tests/serpapi_image_fetch.py "SpyCloud logo site:spycloud.com"
  # Optionally set OUTPUT=./temp/logo.jpg and NUM=5

What it does:
  - Calls SerpAPI Google Images (tbm=isch) for the given query.
  - Downloads the first image result to OUTPUT (default: ./temp/serpapi_image.jpg).
  - Prints the chosen result (title, original, thumbnail, source).
"""

import os
import sys
import json
import pathlib
import requests


def fetch_images(query: str, num: int, api_key: str):
    params = {
        "engine": "google",
        "q": query,
        "tbm": "isch",
        "num": num,
        "api_key": api_key,
    }
    resp = requests.get("https://serpapi.com/search.json", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("images_results") or []
    if not results:
        raise RuntimeError("No images_results in response")
    return results


def download_image(url: str, dest: pathlib.Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    return dest


def main():
    if len(sys.argv) < 2:
        print("Usage: SERPAPI_API_KEY=... python3 tests/serpapi_image_fetch.py \"<query>\"")
        sys.exit(1)

    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        print("SERPAPI_API_KEY env is required")
        sys.exit(1)

    query = sys.argv[1]
    num = int(os.environ.get("NUM") or "3")
    output = pathlib.Path(os.environ.get("OUTPUT") or "./temp/serpapi_image.jpg")

    results = fetch_images(query, num=num, api_key=api_key)
    first = results[0]
    original_url = first.get("original") or first.get("image")
    thumb = first.get("thumbnail")
    source = first.get("link")
    title = first.get("title")

    if not original_url:
        raise RuntimeError("No original image URL found in first result")

    saved = download_image(original_url, output)
    print(json.dumps(
        {
            "saved_to": str(saved),
            "title": title,
            "original": original_url,
            "thumbnail": thumb,
            "source": source,
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()

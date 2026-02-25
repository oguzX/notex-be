from typing import Any, Dict, List

import redis
from app.mcp_server.server import mcp
import re
import requests
from bs4 import BeautifulSoup

BASE_PAGE_URL = "https://www.istanbuleczaciodasi.org.tr/nobetci-eczane/"
POST_URL = "https://www.istanbuleczaciodasi.org.tr/nobetci-eczane/index.php"

import os
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/5"))

def get_token_from_page(session: requests.Session) -> str:
    page_resp = session.get(BASE_PAGE_URL, timeout=20)
    page_resp.raise_for_status()
    return extract_h_token(page_resp.text)

def extract_h_token(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    elem = soup.select_one("#h")
    if elem and elem.get("value"):
        return elem["value"].strip()

    match = re.search(r'id=["\']h["\'][^>]*value=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    raise RuntimeError("Could not find h token in page HTML.")

def get_token(session: requests.Session) -> str:
    token = redis_client.get("pharmacy_h_token")
    if token:
        return token.decode("utf-8")
    
    h_token = get_token_from_page(session)
    redis_client.setex("pharmacy_h_token", 300, h_token)  # Cache for 5 minutes
    return h_token
    

def fetch_pharmacies(district: str = "Adalar") -> List[Dict[str, Any]]:
    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        h_token = get_token(session)

        payload = {
            "jx": "1",
            "islem": "get_ilce_eczane",
            "h": h_token,
            "ilce": district,
        }

        post_headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE_PAGE_URL,
        }

        post_resp = session.post(POST_URL, data=payload, headers=post_headers, timeout=20)
        post_resp.raise_for_status()

        try:
            data = post_resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Endpoint did not return JSON. First 300 chars: {post_resp.text[:300]}") from exc

        if isinstance(data, dict):
            # Some APIs wrap list in a key
            for key in ("data", "results", "markers", "eczaneler"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            raise RuntimeError(f"JSON is dict but no known list key found. Keys: {list(data.keys())}")

        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected JSON type: {type(data).__name__}")

        return data

@mcp.tool
async def pharmacy_search(name: str | None = None, district: str = "Adalar") -> Dict[str, Any]:
    """Search pharmacies by name/city/district."""
    try:
        results = fetch_pharmacies(district=district)

        filtered = []
        for item in results:
            pharmacy_name = item.get("name") or item.get("eczane_adi") or item.get("title") or ""
            if name is None or name.lower() in pharmacy_name.lower():
                filtered.append({
                    "name": pharmacy_name,
                    "address": item.get("address") or item.get("adres"),
                    "phone": item.get("phone") or item.get("tel"),
                    "latitude": item.get("lat") or item.get("latitude"),
                    "longitude": item.get("lng") or item.get("longitude"),
                    "raw": item,  # debugging için faydalı
                })

        return {
            "count": len(filtered),
            "city": 'Istanbul',
            "district": district,
            "pharmacies": filtered,
        }
    except Exception as e:
        return {"error": str(e)}
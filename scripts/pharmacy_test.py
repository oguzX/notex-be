import re
import requests
from bs4 import BeautifulSoup

BASE_PAGE_URL = "https://www.istanbuleczaciodasi.org.tr/nobetci-eczane/"
POST_URL = "https://www.istanbuleczaciodasi.org.tr/nobetci-eczane/index.php"

def extract_h_token(html: str) -> str:
    # 1) Preferred: hidden input with id="h"
    soup = BeautifulSoup(html, "html.parser")
    elem = soup.select_one("#h")
    if elem and elem.get("value"):
        return elem["value"].strip()

    # 2) Fallback regex in case HTML structure changes
    match = re.search(r'id=["\']h["\'][^>]*value=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    raise RuntimeError("Could not find h token in page HTML.")

def fetch_pharmacies(city: str = "İstanbul", district: str = "Adalar"):
    with requests.Session() as session:
        # Optional but useful headers
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        # Step 1: Get page (this also establishes cookies/session)
        page_resp = session.get(BASE_PAGE_URL, timeout=20)
        page_resp.raise_for_status()

        h_token = extract_h_token(page_resp.text)
        print("h token:", h_token)

        # Step 2: POST with same session + token
        payload = {
            "jx": "1",
            "islem": "get_eczane_markers",
            "h": h_token,
            # Depending on endpoint expectations, these may or may not be required:
            "il": city,
            "ilce": district,
        }

        post_headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE_PAGE_URL,
        }

        post_resp = session.post(POST_URL, data=payload, headers=post_headers, timeout=20)
        post_resp.raise_for_status()

        # Often JSON, but sometimes text/html
        content_type = post_resp.headers.get("Content-Type", "")
        if "application/json" in content_type:
            return post_resp.json()
        return post_resp.text

if __name__ == "__main__":
    result = fetch_pharmacies(city="İstanbul", district="Adalar")
    print(result)
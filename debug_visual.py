#!/usr/bin/env python3
"""Midlertidig diagnose: hent 4 faktiske sidebilder for én kjede fra
Tjek-APIet og skriv dem ut som base64 i jobb-loggen, for et reelt
visuelt stikkprøve-tilbudstall (se kundeavis_bot.py sin docstring for
bakgrunn). Kjøres én kjede om gangen — jobb-loggens størrelsesgrense
kutter av innholdet hvis for mye base64 skrives ut i én kjøring."""
import base64
import requests

TJEK_API_BASE = "https://squid-api.tjek.com/v2"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

TARGETS = [
    ("meny", "4333pm"),
]
PAGES_PER_CHAIN = 4

for name, dealer_id in TARGETS:
    url = f"{TJEK_API_BASE}/catalogs?dealer_id={dealer_id}&order_by=-publication_date&offset=0&limit=1"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    catalog = r.json()[0]
    print(f"### {name} catalog_id={catalog['id']} label={catalog.get('label')!r} "
          f"page_count={catalog.get('page_count')} offer_count={catalog.get('offer_count')}")

    pages_url = f"{TJEK_API_BASE}/catalogs/{catalog['id']}/pages?w=600"
    r = requests.get(pages_url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    pages = r.json()

    for idx, page in enumerate(pages[:PAGES_PER_CHAIN], start=1):
        page_url = page.get("view") or page.get("zoom") or page.get("thumb")
        r = requests.get(page_url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        print(f"### {name} p{idx} content_type={r.headers.get('Content-Type')} bytes={len(r.content)}")
        b64 = base64.b64encode(r.content).decode()
        print(f"### {name} p{idx} BASE64_START")
        for i in range(0, len(b64), 200):
            print(b64[i:i + 200])
        print(f"### {name} p{idx} BASE64_END")

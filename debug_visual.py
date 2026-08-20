#!/usr/bin/env python3
"""Midlertidig diagnose: hent ÉN faktisk sideside (REMA + Bunnpris, side 1)
fra Tjek-APIet og skriv den ut som base64 i jobb-loggen, slik at innholdet
kan avkodes og synes visuelt utenfor GitHub Actions-miljøet (som har full
nettilgang, i motsetning til utviklingssandboksen)."""
import base64
import requests

TJEK_API_BASE = "https://squid-api.tjek.com/v2"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

TARGETS = [
    ("rema1000", "faa0Ym"),
    ("bunnpris", "5b11sm"),
]

for name, dealer_id in TARGETS:
    url = f"{TJEK_API_BASE}/catalogs?dealer_id={dealer_id}&order_by=-publication_date&offset=0&limit=1"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    catalog = r.json()[0]
    print(f"### {name} catalog_id={catalog['id']} label={catalog.get('label')!r}")

    pages_url = f"{TJEK_API_BASE}/catalogs/{catalog['id']}/pages?w=350"
    r = requests.get(pages_url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    pages = r.json()
    page1_url = pages[0].get("view") or pages[0].get("zoom") or pages[0].get("thumb")
    print(f"### {name} page1_url={page1_url}")

    r = requests.get(page1_url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    content_type = r.headers.get("Content-Type")
    print(f"### {name} content_type={content_type} bytes={len(r.content)}")

    b64 = base64.b64encode(r.content).decode()
    print(f"### {name} BASE64_START")
    # skriv i faste linjelengder slik at det er enkelt å slå sammen igjen
    for i in range(0, len(b64), 200):
        print(b64[i:i + 200])
    print(f"### {name} BASE64_END")

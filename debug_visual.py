#!/usr/bin/env python3
"""Midlertidig diagnose: brukeren ga en konkret regional Coop Obs-URL
(kundeavis-obs.coop.no/sorvest/) som kan avsløre en region-spesifikk
Tjek/ShopGun dealer-ID, samme mønster som avdekket Bunnpris sin
dealer-ID (data-business-id i sgn-sdk-embed på butikksiden deres)."""
import re
import requests

URL = "https://kundeavis-obs.coop.no/sorvest/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

r = requests.get(URL, headers=HEADERS, timeout=20, allow_redirects=True)
print(f"status={r.status_code} final_url={r.url}")
html = r.text
print(f"html_length={len(html)}")

# Se etter Tjek/ShopGun sin sgn-sdk-embed med data-business-id, samme som Bunnpris
for pattern in [
    r'data-business-id="([^"]+)"',
    r'data-api-key="([^"]+)"',
    r'sgn-sdk[^"]*"',
    r'shopgun[^"]*',
    r'tjek\.com[^"\'\s]*',
    r'business[_-]?id["\':\s]+([a-zA-Z0-9_-]+)',
    r'dealer[_-]?id["\':\s]+([a-zA-Z0-9_-]+)',
]:
    matches = re.findall(pattern, html, re.IGNORECASE)
    if matches:
        print(f"MATCH '{pattern}': {matches[:10]}")

# Print et utsnitt rundt evt. "sgn-sdk" eller "tjek" for kontekst
for keyword in ["sgn-sdk", "tjek.com", "shopgun", "business-id"]:
    idx = html.lower().find(keyword.lower())
    if idx != -1:
        print(f"\n--- kontekst rundt '{keyword}' (idx={idx}) ---")
        print(html[max(0, idx - 300):idx + 300])

# Hvis siden er en tung SPA uten synlig HTML-innhold, print starten uansett
print("\n--- html start (2000 tegn) ---")
print(html[:2000])

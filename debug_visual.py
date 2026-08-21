#!/usr/bin/env python3
"""Midlertidig diagnose runde 2: siden bruker iPaper (ikke Tjek).
PaperGuid=38fac292-5001-498e-9d88-871797c97743 ble funnet i og:image
meta-taggen (base64-dekodet JSON). Let etter iPaper sitt eget
API-/CDN-mønster for sidebilder i resten av HTML-en (scripts, iframes,
json-blobs) som denne enkle print(html[:2000]) ikke fanget opp forrige
runde."""
import re
import requests

URL = "https://kundeavis-obs.coop.no/sorvest/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
PAPER_GUID = "38fac292-5001-498e-9d88-871797c97743"

r = requests.get(URL, headers=HEADERS, timeout=20, allow_redirects=True)
html = r.text
print(f"html_length={len(html)}")

print("\n--- alle <script src=...> ---")
for m in re.findall(r'<script[^>]+src="([^"]+)"', html):
    print(m)

print("\n--- alle <iframe ...> ---")
for m in re.finditer(r'<iframe[^>]*>', html):
    print(m.group())

print("\n--- forekomster av PaperGuid i html ---")
for m in re.finditer(re.escape(PAPER_GUID), html):
    idx = m.start()
    print(f"idx={idx}: ...{html[max(0,idx-150):idx+150]}...")

print("\n--- forekomster av 'ipaper' (case-insensitive), med kontekst ---")
for m in re.finditer(r'ipaper', html, re.IGNORECASE):
    idx = m.start()
    ctx = html[max(0, idx - 100):idx + 150]
    if "cdn.ipaper.io/iPaper/Files" not in ctx:  # dropp favicon-støy
        print(f"idx={idx}: ...{ctx}...")

print("\n--- inline <script> blokker (uten src), forkortet ---")
for m in re.finditer(r'<script(?![^>]*src=)[^>]*>(.*?)</script>', html, re.DOTALL):
    body = m.group(1).strip()
    if body:
        print(f"[{len(body)} tegn] {body[:500]}")
        print("...")

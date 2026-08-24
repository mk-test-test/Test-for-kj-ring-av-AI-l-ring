#!/usr/bin/env python3
"""Diagnose runde 4 (Playwright): tidligere runder fant at iPaper sin
side-bilde-URL ikke lot seg gjette ut fra statisk HTML/JSON alene. Denne
bruker en ekte (headless) nettleser og lytter på ALLE nettverksresponser
mens siden lastes, for å fange opp de faktiske URL-ene iPaper sitt
JS-bibliotek ber om for sidebildene."""
from playwright.sync_api import sync_playwright

URL = "https://kundeavis-obs.coop.no/sorvest/"

fangede_bilder = []
alle_ipaper_requests = []

def on_response(response):
    url = response.url
    if "ipaper" in url.lower():
        alle_ipaper_requests.append((response.status, url))
    ct = response.headers.get("content-type", "")
    if ct.startswith("image/") and "ipaper" in url.lower():
        fangede_bilder.append((response.status, ct, url))

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.on("response", on_response)

    page.goto(URL, wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(3000)

    # Prøv å klikke/scrolle for å trigge lasting av flere sider, hvis mulig
    try:
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(2000)
    except Exception as e:
        print(f"Kunne ikke scrolle: {e}")

    browser.close()

print(f"Totalt antall ipaper-relaterte nettverkskall: {len(alle_ipaper_requests)}")
print(f"Antall FAKTISKE bilderesponser (content-type=image/*): {len(fangede_bilder)}")

print("\n--- alle ipaper-URLer (første 40) ---")
for status, url in alle_ipaper_requests[:40]:
    print(f"{status} {url}")

print("\n--- bilderesponser ---")
for status, ct, url in fangede_bilder[:40]:
    print(f"{status} {ct} {url}")

#!/usr/bin/env python3
"""Diagnose runde 8: runde 7 viste at hent_publications_etilbudsavis() ga
"Antall publications: 0" for alle 4 kjeder, og RASKT (~150ms totalt for 4
HTTP-kall) - for raskt til å være en ekte HTML-side-nedlasting med reelt
innhold. Marker-strengen '"publications":[' ble aldri funnet (ingen
unntak ble kastet, dvs. vi traff idx==-1-grenen). Dette scriptet dumper
status_code, respons-lengde, starten av HTML-en, og om noen kjente
markører (etilbudsavis, cookie/captcha, publications) finnes i det hele
tatt - for å finne ut om URL-mønsteret/slug-ene er feil, om siden krever
JS-rendring, eller om vi blir blokkert."""
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KundeavisBot/1.0)"}
SLUGS = ["REMA-1000", "KIWI", "SPAR", "Bunnpris"]

for slug in SLUGS:
    url = f"https://etilbudsavis.no/{slug}"
    print(f"\n{'='*20} {slug} {'='*20}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
    except Exception as e:
        print(f"REQUEST-FEIL: {e}")
        continue
    print(f"status={r.status_code} final_url={r.url} lengde={len(r.text)}")
    print(f"content-type={r.headers.get('content-type')}")
    for marker in ['"publications"', "publications", "etilbudsavis", "cookie", "captcha", "<title", "Just a moment", "Cloudflare"]:
        print(f"  inneholder {marker!r}: {marker in r.text}")
    print("--- Første 800 tegn ---")
    print(r.text[:800])
    print("--- Siste 300 tegn ---")
    print(r.text[-300:])

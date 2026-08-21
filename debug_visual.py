#!/usr/bin/env python3
"""Midlertidig diagnose: sjekk om Coop Obs sin dealer-ID (funnet tidligere
denne økten via samme GitHub-søk som de 6 andre kjedene, men aldri testet)
gir en ekte, aktuell katalog — og om den er generell for hele Coop Obs-
kjeden eller spesifikk for én butikk (brukeren spurte etter Mariero)."""
import requests

TJEK_API_BASE = "https://squid-api.tjek.com/v2"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

DEALER_ID = "51dawm"

url = f"{TJEK_API_BASE}/catalogs?dealer_id={DEALER_ID}&order_by=-publication_date&offset=0&limit=3"
r = requests.get(url, headers=HEADERS, timeout=20)
print(f"status={r.status_code}")
r.raise_for_status()
kataloger = r.json()
print(f"antall kataloger funnet: {len(kataloger)}")
for k in kataloger:
    print("---")
    print(f"id={k.get('id')} label={k.get('label')!r}")
    print(f"run_from={k.get('run_from')} run_till={k.get('run_till')}")
    print(f"page_count={k.get('page_count')} offer_count={k.get('offer_count')}")
    print(f"dealer_id={k.get('dealer_id')} store_id={k.get('store_id')}")

# Hent dealer-info for å se om navnet indikerer en bestemt butikk (f.eks. Mariero)
dealer_url = f"{TJEK_API_BASE}/dealers/{DEALER_ID}"
r2 = requests.get(dealer_url, headers=HEADERS, timeout=20)
print(f"\ndealer-info status={r2.status_code}")
if r2.ok:
    print(r2.json())

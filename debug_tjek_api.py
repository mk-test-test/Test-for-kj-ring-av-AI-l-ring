#!/usr/bin/env python3
"""Midlertidig diagnose-script: tester Tjek (tidl. ShopGun) sitt offentlige
REST-API direkte (squid-api.tjek.com) med dealer-ID-er funnet via
GitHub-søk (holgersetten/ukeshandel.no, tobiaseis/Food-App), for å se om
dette gir et mer pålitelig alternativ til nettleser-scraping av kjedenes
egne sider. Kjøres i et miljø med ekte nettverkstilgang (GitHub Actions).
Slettes når funnene er brukt til å bygge om kundeavis_bot.py."""

import json

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
BASE = "https://squid-api.tjek.com/v2"

# Kandidat-dealer-ID-er funnet via GitHub-søk i eksterne, ikke-tilknyttede
# prosjekter (holgersetten/ukeshandel.no sin stores.ts, samt en alternativ
# REMA-ID fra tobiaseis/Food-App sine intercepterte data).
KANDIDATER = {
    "rema1000": ["faa0Ym", "11deC"],
    "kiwi": ["257bxm"],
    "coop-extra": ["80742m"],
    "meny": ["4333pm"],
    "spar": ["c062vm"],
    "bunnpris": ["5b11sm"],  # bekreftet uavhengig via sgn-sdk data-business-id på bunnpris.no
}

for kjede, dealer_ids in KANDIDATER.items():
    print(f"\n############ {kjede} ############")
    for dealer_id in dealer_ids:
        url = f"{BASE}/catalogs?dealer_id={dealer_id}&order_by=-publication_date&offset=0&limit=1"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            print(f"  dealer_id={dealer_id} -> HTTP {r.status_code}")
            if r.status_code != 200:
                print("   ", r.text[:300])
                continue
            data = r.json()
            if not data:
                print("    Tom liste - ingen katalog funnet for denne dealer_id")
                continue
            cat = data[0]
            print(f"    id={cat.get('id')} label={cat.get('label')!r}")
            print(f"    run_from={cat.get('run_from')} run_till={cat.get('run_till')}")
            print(f"    page_count={cat.get('page_count')} offer_count={cat.get('offer_count')}")
            print(f"    pdf_url={cat.get('pdf_url')}")

            pdf_url = cat.get("pdf_url")
            if pdf_url:
                pr = requests.get(pdf_url, headers=HEADERS, timeout=20, allow_redirects=True)
                is_pdf = pr.content[:5] == b"%PDF-"
                print(f"    PDF-nedlasting: HTTP {pr.status_code}, {len(pr.content)} bytes, gyldig PDF-header: {is_pdf}")

            catalog_id = cat.get("id")
            pages_url = f"{BASE}/catalogs/{catalog_id}/pages?w=1000"
            ppr = requests.get(pages_url, headers=HEADERS, timeout=15)
            print(f"    /pages -> HTTP {ppr.status_code}")
            if ppr.status_code == 200:
                pages = ppr.json()
                print(f"    /pages type={type(pages).__name__} lengde={len(pages) if hasattr(pages, '__len__') else '?'}")
                print(f"    /pages[0:2] raw={json.dumps(pages[:2], ensure_ascii=False)[:600]}")
                first_img_url = None
                if isinstance(pages, list) and pages:
                    p0 = pages[0]
                    if isinstance(p0, str):
                        first_img_url = p0
                    elif isinstance(p0, dict):
                        first_img_url = p0.get("view") or p0.get("zoom") or p0.get("image") or p0.get("url")
                if first_img_url:
                    ir = requests.get(first_img_url, headers=HEADERS, timeout=15)
                    print(f"    Nedlasting av side 1-bilde ({first_img_url}): HTTP {ir.status_code}, {len(ir.content)} bytes, content-type={ir.headers.get('content-type')}")
            else:
                print("    ", ppr.text[:300])
        except Exception as e:
            print(f"    FEIL: {e}")

print("\n\nFERDIG.")

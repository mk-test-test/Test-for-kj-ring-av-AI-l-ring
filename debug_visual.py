#!/usr/bin/env python3
"""Diagnose runde 7: bruker­innsendt hent_publications_etilbudsavis() (henter
JSON direkte fra etilbudsavis.no sin server-rendrede side) for REMA-1000,
KIWI, SPAR og Bunnpris. Formål:

1. Se nøyaktig hva publications-objektene inneholder (felt, evt. dealer/
   katalog-ID, run_from/run_till, sidetall, bilde-URL-mønster).
2. Sjekke om "view"-bildet sin URL følger et gjettbart p-1.webp/p-2.webp-
   mønster som gir alle sidene, eller om det finnes et helt annet felt/
   endepunkt for det (f.eks. et innebygd sider-array, eller en id som kan
   brukes mot squid-api.tjek.com/v2/catalogs/{id}/pages - det endepunktet
   VET vi allerede virker for disse kjedene).
3. Avklare om etilbudsavis.no i bunn og grunn er Tjek/ShopGun sin egen
   forbrukerside (samme datakilde vi allerede bruker via squid-api.tjek.com),
   eller en reelt annen kilde."""
import json

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KundeavisBot/1.0)"}


def hent_publications_etilbudsavis(chain_slug: str) -> list:
    url = f"https://etilbudsavis.no/{chain_slug}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()

    marker = '"publications":['
    idx = r.text.find(marker)
    if idx == -1:
        return []
    search_start = max(0, idx - 200)
    obj_start = r.text.rfind('{"category"', search_start, idx)
    obj, _ = json.JSONDecoder().raw_decode(r.text[obj_start:])
    return obj.get("publications", [])


SLUGS = ["REMA-1000", "KIWI", "SPAR", "Bunnpris"]

for slug in SLUGS:
    print(f"\n{'='*20} {slug} {'='*20}")
    try:
        pubs = hent_publications_etilbudsavis(slug)
    except Exception as e:
        print(f"FEIL: {e}")
        continue

    print(f"Antall publications: {len(pubs)}")
    if not pubs:
        continue

    pub = pubs[0]
    print(f"Nøkler i første publication: {sorted(pub.keys())}")
    print(json.dumps(pub, ensure_ascii=False, indent=2)[:3000])

    # Let etter et bilde-/view-felt uansett hvor det måtte ligge
    def finn_bilde_urler(obj, path=""):
        funnet = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and ("http" in v) and (
                    ".jpg" in v or ".webp" in v or ".png" in v
                ):
                    funnet.append((f"{path}.{k}", v))
                else:
                    funnet.extend(finn_bilde_urler(v, f"{path}.{k}"))
        elif isinstance(obj, list):
            for i, v in enumerate(obj[:3]):
                funnet.extend(finn_bilde_urler(v, f"{path}[{i}]"))
        return funnet

    bilder = finn_bilde_urler(pub)
    print(f"\nFunne bilde-URLer ({len(bilder)}):")
    for felt, url in bilder:
        print(f"  {felt} = {url}")

    # Test p-1/p-2/p-3-varianter for hver funnet bilde-URL
    for felt, url in bilder:
        if "p-1" in url or "p_1" in url or "/1." in url:
            for n in [1, 2, 3]:
                test_url = url.replace("p-1", f"p-{n}").replace("p_1", f"p_{n}")
                try:
                    resp = requests.head(test_url, headers=HEADERS, timeout=15, allow_redirects=True)
                    print(f"  TEST side {n}: {resp.status_code} {test_url}")
                except Exception as e:
                    print(f"  TEST side {n}: FEIL {e}")

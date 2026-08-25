#!/usr/bin/env python3
"""Diagnose runde 9: runde 8 viste at etilbudsavis.no er en client-rendret
SPA (React/lignende) som hydrerer data via <app-data data-key="BASE64">
JSON-INNHOLD</app-data>-tagger, der data-key er base64(JSON.stringify(
queryKey)) i TanStack Query-stil (f.eks. ["offerAgents",null]). Den
opprinnelige hent_publications_etilbudsavis()-funksjonen lette etter en
literal '"publications":[' streng, som ikke finnes i denne strukturen.

Dette scriptet parser ALLE <app-data>-tagger, dekoder nøkkelen fra
base64, og printer (dekodet_nøkkel, innholdslengde, innhold-preview) for
hver - for å finne nøyaktig hvilken tag som inneholder katalog-/
publikasjonsdata, og se om dataene der gir oss det vi trenger (id/URL/
sidetall) for å bygge PDF-er."""
import base64
import json
import re

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KundeavisBot/1.0)"}

APP_DATA_RE = re.compile(
    r'<app-data data-key="([^"]+)" data-size="(\d+)" data-status="([^"]+)">(.*?)</app-data>',
    re.DOTALL,
)


def hent_app_data(slug: str):
    url = f"https://etilbudsavis.no/{slug}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


for slug in ["REMA-1000", "Bunnpris"]:
    print(f"\n{'='*20} {slug} {'='*20}")
    html = hent_app_data(slug)
    matches = APP_DATA_RE.findall(html)
    print(f"Antall <app-data>-tagger funnet: {len(matches)}")

    for key_b64, size, status, content in matches:
        try:
            padded = key_b64 + "=" * (-len(key_b64) % 4)
            decoded_key = base64.b64decode(padded).decode("utf-8", errors="replace")
        except Exception as e:
            decoded_key = f"(kunne ikke dekode: {e})"
        print(f"\n--- key={decoded_key} size={size} status={status} ---")
        print(f"innhold ({len(content)} tegn): {content[:400]}")

        # Prøv å parse innholdet som JSON hvis det ser lovende ut
        if any(w in decoded_key.lower() for w in ["catalog", "publication", "offer", "dealer", "paper"]):
            try:
                data = json.loads(content.replace("&quot;", '"').replace("&amp;", "&"))
                print(f"PARSET JSON (type={type(data).__name__}):")
                print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
            except Exception as e:
                print(f"Kunne ikke parse som JSON: {e}")

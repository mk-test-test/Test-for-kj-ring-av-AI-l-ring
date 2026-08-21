#!/usr/bin/env python3
"""Diagnose runde 3: fant window.staticSettings sin "aws" blokk:
  aws.url = https://cdn.ipaper.io/iPaper/Papers/{guid}/
  aws.policy = token=...&token_path=%2fiPaper%2fPapers%2f{guid}%2fPages%2f&expires=...
Dette antyder sidebilder ligger under .../Papers/{guid}/Pages/{n}.<ext>.
Søk etter en eksplisitt eksempel-URL i JSON-en for å bekrefte filnavn-
mønsteret, og prøv deretter å faktisk laste ned side 1 med noen
kandidat-mønstre."""
import json
import re
import requests

URL = "https://kundeavis-obs.coop.no/sorvest/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

r = requests.get(URL, headers=HEADERS, timeout=20, allow_redirects=True)
html = r.text

# Hent ut hele window.staticSettings JSON-blokken
m = re.search(r'window\.staticSettings\s*=\s*(\{.*?\});', html, re.DOTALL)
if not m:
    print("FANT IKKE staticSettings-blokken i det hele tatt")
    raise SystemExit(1)

raw = m.group(1)
print(f"staticSettings lengde: {len(raw)}")

try:
    settings = json.loads(raw)
    print("JSON parset OK")
except Exception as e:
    print(f"JSON parse feilet: {e}")
    settings = None

if settings:
    print(f"\npaperId={settings.get('paperId')} licenseId={settings.get('licenseId')}")
    aws = settings.get("aws", {})
    print(f"aws.url={aws.get('url')}")
    print(f"aws.fileUrl={aws.get('fileUrl')}")
    print(f"aws.fileOptimizedUrl={aws.get('fileOptimizedUrl')}")
    print(f"aws.policy={aws.get('policy')}")

    # Let etter alt som ser ut som en side-bilde-URL et sted i hele JSON-strukturen
    def finn_urler(obj, treff):
        if isinstance(obj, str):
            if "Pages/" in obj or re.search(r'\.(jpg|jpeg|png|webp)', obj, re.IGNORECASE):
                treff.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                finn_urler(v, treff)
        elif isinstance(obj, list):
            for v in obj:
                finn_urler(v, treff)

    treff = []
    finn_urler(settings, treff)
    print(f"\nFant {len(treff)} URL-lignende strenger med 'Pages/' eller bildeendelse:")
    for t in treff[:20]:
        print(f"  {t}")

    # Prøv å konstruere en kandidat-URL for side 1 basert på aws.url + policy
    if aws.get("url") and aws.get("policy"):
        for ext in ["jpg", "webp", "png"]:
            for name in [f"1.{ext}", f"01.{ext}", f"Page1.{ext}", f"page-1.{ext}"]:
                candidate = f"{aws['url']}Pages/{name}?{aws['policy']}"
                try:
                    rr = requests.get(candidate, headers=HEADERS, timeout=15)
                    print(f"KANDIDAT {candidate[:120]}... -> status={rr.status_code} content-type={rr.headers.get('Content-Type')} bytes={len(rr.content)}")
                except Exception as e:
                    print(f"KANDIDAT {candidate[:120]}... -> FEIL {e}")

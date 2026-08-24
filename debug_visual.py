#!/usr/bin/env python3
"""Diagnose runde 5 (ren requests, ingen nettleser): runde 4 (Playwright)
fant det virkelige URL-mønsteret for iPaper sine sidebilder:
  https://cdn.ipaper.io/iPaper/Papers/{guid}/Pages/{n}/Zoom.jpg?token=...&token_path=...&expires=...

Spørsmålet nå: kan token/token_path/expires hentes direkte fra
window.staticSettings i den statiske HTML-en (uten nettleser), og gjenbrukes
til å bygge URL-er for ALLE sidene selv? Hvis ja, trenger vi ikke Playwright
i selve produksjonsboten - bare requests + regex/json, akkurat som Tjek-delen.
"""
import json
import re

import requests

URL = "https://kundeavis-obs.coop.no/sorvest/"

r = requests.get(URL, timeout=20)
print(f"GET {URL} -> {r.status_code}, {len(r.text)} bytes")

m = re.search(r"window\.staticSettings\s*=\s*(\{.*?\});", r.text, re.DOTALL)
if not m:
    print("FANT IKKE window.staticSettings i HTML-en")
else:
    data = json.loads(m.group(1))
    aws = data.get("aws", {})
    print("paperId:", data.get("paperId"))
    print("licenseId:", data.get("licenseId"))
    print("aws.url:", aws.get("url"))
    print("aws.fileUrl:", aws.get("fileUrl"))
    print("aws.fileOptimizedUrl:", aws.get("fileOptimizedUrl"))
    print("aws.policy:", aws.get("policy"))

    policy = aws.get("policy", "")
    base = aws.get("url", "")
    if policy and base:
        for n in [1, 2, 5]:
            test_url = f"{base}Pages/{n}/Zoom.jpg?{policy}"
            resp = requests.get(test_url, timeout=20)
            ct = resp.headers.get("content-type", "?")
            print(f"Side {n}: {resp.status_code} {ct} {len(resp.content)} bytes -> {test_url}")

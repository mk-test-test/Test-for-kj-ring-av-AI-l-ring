#!/usr/bin/env python3
"""Midlertidig diagnose-script: dumper input-felt, knapper og bilde-/PDF-
URL-mønstre for REMA 1000 sin kundeavis-side og mattilbud.no-fallbacken,
til bruk for å rette selectorene i kundeavis_bot.py. Skal kjøres i et miljø
med ekte nettverkstilgang (f.eks. GitHub Actions), ikke i utviklingssandkassen.
Slettes når selectorene er rettet og bekreftet."""

import json
import re

from kundeavis_bot import dismiss_cookie_banner, _chromium_launch_kwargs
from playwright.sync_api import sync_playwright


def dump_inputs_and_buttons(page, label):
    print(f"\n=== {label}: input-elementer ===")
    inputs = page.eval_on_selector_all(
        "input",
        """els => els.map(e => ({
            type: e.type, placeholder: e.placeholder, name: e.name, id: e.id,
            ariaLabel: e.getAttribute('aria-label'),
            className: e.className, visible: e.offsetParent !== null
        }))""",
    )
    for i in inputs:
        print(json.dumps(i, ensure_ascii=False))

    print(f"\n=== {label}: knapper ===")
    buttons = page.eval_on_selector_all(
        "button",
        """els => els.map(e => ({
            text: e.innerText.trim().slice(0, 60), id: e.id,
            className: e.className, visible: e.offsetParent !== null
        }))""",
    )
    for b in buttons:
        if b["text"] or b["id"]:
            print(json.dumps(b, ensure_ascii=False))


print("############ REMA 1000 — rema.no/kundeavis ############")
with sync_playwright() as p:
    browser = p.chromium.launch(**_chromium_launch_kwargs())
    page = browser.new_page()
    page.goto("https://rema.no/kundeavis", timeout=30_000, wait_until="networkidle")
    dismiss_cookie_banner(page)
    page.wait_for_timeout(1000)
    dump_inputs_and_buttons(page, "rema.no/kundeavis")
    page.screenshot(path="debug_rema.png", full_page=True)
    print("\nSide-URL etter navigasjon:", page.url)
    browser.close()

print("\n\n############ REMA 1000 — mattilbud.no fallback ############")
with sync_playwright() as p:
    browser = p.chromium.launch(**_chromium_launch_kwargs())
    page = browser.new_page()
    page.goto("https://mattilbud.no/kundeaviser/rema-1000-no", timeout=30_000, wait_until="networkidle")
    dismiss_cookie_banner(page)
    page.wait_for_timeout(1000)
    html = page.content()
    print(f"HTML-lengde: {len(html)} tegn")

    imgs = re.findall(r'https?://[^\s"\'\\]+\.(?:jpe?g|png|webp)(?:\?[^\s"\'\\]*)?', html, re.IGNORECASE)
    print(f"\nFant {len(imgs)} bilde-URLer (viser inntil 40):")
    for u in imgs[:40]:
        print(" ", u)

    pdfs = re.findall(r'https?://[^\s"\']+\.pdf', html, re.IGNORECASE)
    print(f"\nFant {len(pdfs)} PDF-URLer:")
    for u in pdfs[:10]:
        print(" ", u)

    page.screenshot(path="debug_mattilbud_rema.png", full_page=True)
    browser.close()

print("\n\nFERDIG.")

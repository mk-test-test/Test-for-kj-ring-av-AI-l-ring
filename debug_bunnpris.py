#!/usr/bin/env python3
"""Midlertidig diagnose-script: undersøker en butikkspesifikk Bunnpris-side
med #kundeavis-anker, for å se hva slags kundeavis-visning som faktisk
brukes der (PDF-lenke, bilde-serie, iframe-embed, etc.). Kjøres i et miljø
med ekte nettverkstilgang (GitHub Actions), ikke i utviklingssandkassen.
Slettes når funnene er brukt til å rette strategien i kundeavis_bot.py."""

import json
import re

from kundeavis_bot import dismiss_cookie_banner, _chromium_launch_kwargs
from playwright.sync_api import sync_playwright

URL = "https://www.bunnpris.no/butikker/bunnpris-tjensvoll#kundeavis"

print(f"############ Bunnpris Tjensvoll — {URL} ############")
with sync_playwright() as p:
    browser = p.chromium.launch(**_chromium_launch_kwargs())
    page = browser.new_page()
    page.goto(URL, timeout=30_000, wait_until="networkidle")
    dismiss_cookie_banner(page)
    page.wait_for_timeout(3000)

    print("\nSide-URL etter navigasjon:", page.url)
    print("HTML-lengde:", len(page.content()))

    # Se etter elementer knyttet til "kundeavis" i id/class/data-attributter
    print("\n=== Elementer med 'kundeavis' i id/class/data-* ===")
    els = page.eval_on_selector_all(
        "*",
        """els => els.filter(e => {
            const attrs = Array.from(e.attributes || []).map(a => a.name + '=' + a.value).join(' ');
            return /kundeavis/i.test(attrs);
        }).slice(0, 30).map(e => ({
            tag: e.tagName, id: e.id, className: e.className,
            outerHTMLSnippet: e.outerHTML.slice(0, 300)
        }))""",
    )
    for e in els:
        print(json.dumps(e, ensure_ascii=False))

    # Iframes på siden (mange kundeaviser er tredjeparts-embeds)
    print("\n=== Iframes ===")
    iframes = page.eval_on_selector_all(
        "iframe",
        "els => els.map(e => ({src: e.src, id: e.id, className: e.className, title: e.title}))",
    )
    for f in iframes:
        print(json.dumps(f, ensure_ascii=False))

    html = page.content()

    pdfs = re.findall(r'https?://[^\s"\']+\.pdf', html, re.IGNORECASE)
    print(f"\n=== PDF-URLer ({len(pdfs)}) ===")
    for u in pdfs[:10]:
        print(" ", u)

    imgs = re.findall(r'https?://[^\s"\'\\]+\.(?:jpe?g|png|webp)(?:\?[^\s"\'\\]*)?', html, re.IGNORECASE)
    print(f"\n=== Bilde-URLer ({len(imgs)}), viser inntil 20 ===")
    for u in imgs[:20]:
        print(" ", u)

    # Eksterne script-/embed-kilder (Tjek/ShopGun/etc. lastes ofte fra 3.parts-domener)
    scripts = page.eval_on_selector_all(
        "script[src]", "els => els.map(e => e.src)"
    )
    ekstern = [s for s in scripts if s and "bunnpris.no" not in s]
    print(f"\n=== Eksterne script-kilder ({len(ekstern)}) ===")
    for s in ekstern[:20]:
        print(" ", s)

    page.screenshot(path="debug_bunnpris.png", full_page=True)
    browser.close()

print("\n\nFERDIG.")

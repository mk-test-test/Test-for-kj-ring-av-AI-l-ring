#!/usr/bin/env python3
"""
kundeavis_bot.py — Henter norske dagligvarekjeders kundeaviser for Stavanger-
regionen som PDF, og lagrer dem i en ukesmappe.

VIKTIG — LES FØR BRUK
----------------------
Dette scriptet er et FUNGERENDE UTGANGSPUNKT, ikke en ferdig testet løsning.
Det er bygget ut fra offentlig informasjon om hvordan kjedene publiserer
kundeaviser (pr. august 2026), men nettsidene endrer seg jevnlig, og noen
URL-er/selectorer under er merket "TODO/VERIFISER" fordi de må sjekkes mot
den faktiske siden i din nettleser (F12 → Inspiser) før de vil fungere
pålitelig.

Scriptet kunne IKKE testes mot de faktiske butikk-nettstedene i miljøet der
denne koden ble skrevet (nettverkstilgangen der er begrenset til
utviklerdomener som pypi/npm/github, ikke rema.no/kiwi.no osv.). Du må
kjøre, teste og feilsøke det i ditt eget miljø.

KJENTE BEGRENSNINGER
---------------------
1. Primærkilde for ALLE kjeder er mattilbud.no (Tjek/tidl. ShopGun sin
   kundeavis-plattform) i stedet for kjedenes egne nettsider — se
   strategy_mattilbud(). Dette ble valgt fordi de enkelte kjedenes egne
   sider ga upålitelige resultater (feil/manglende butikkvalg, ingen
   garanti for at innholdet faktisk var Stavanger-relevant). mattilbud.no
   gir én konsistent kilde for alle kjeder på formen
   mattilbud.no/kundeaviser/<kjede>-no.
   mattilbud.no er en JS-tung SPA og kan i tillegg vise kundeavisen som en
   serie sidebilder i en innebygd JSON-blokk i stedet for én ferdig PDF —
   strategy_mattilbud() prøver derfor (1) direkte PDF-lenke, (2) sette
   sammen sidebilder til én flersidig PDF med Pillow, (3) vanlig
   browser-print av siden (kun gjeldende visning) som siste utvei.
   Punkt 2 (bilde-heuristikken) er IKKE verifisert mot den faktiske
   JSON-strukturen på siden.
2. Kjedens egen offisielle side (chain.fallback_url) brukes kun som
   fallback hvis mattilbud.no feiler helt, via enkel browser-print.
3. dismiss_cookie_banner() prøver flere kjente mønstre (dialog-rolle +
   "Godta"-knapp, OneTrust, Cookiebot, generisk tekstsøk) og logger tydelig
   hvilket forsøk som lyktes eller feilet. Som siste utvei fjernes
   [role="dialog"]-elementer direkte via JavaScript.
4. Respekter robots.txt og bruksvilkår for hver side. Dette scriptet gjør
   kun ett forsøk per kjede per kjøring og bør ikke kjøres oftere enn
   nødvendig (default: ukentlig).

INSTALLASJON
-------------
    pip install requests beautifulsoup4 playwright Pillow
    playwright install chromium

    Hvis "playwright install chromium" ikke får lastet ned nettleseren
    (f.eks. i et sandkasse-/CI-miljø med begrenset nettverkstilgang) og det
    allerede finnes en forhåndsinstallert Chromium under
    $PLAYWRIGHT_BROWSERS_PATH/chromium, oppdager scriptet det automatisk og
    bruker den i stedet (se _chromium_launch_kwargs()).

KJØRING
--------
    python kundeavis_bot.py

PLANLAGT KJØRING — Linux/macOS (cron):
    crontab -e
    0 6 * * 1 /usr/bin/python3 /sti/til/kundeavis_bot.py >> /sti/til/kundeavis.log 2>&1

PLANLAGT KJØRING — Windows (Task Scheduler):
    Opprett en ny oppgave → Trigger: Ukentlig, mandag 06:00
    → Handling: Start et program → python.exe → Argument: full sti til dette scriptet
"""

import io
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ---------------------------------------------------------------------------
# KONFIG
# ---------------------------------------------------------------------------

REGION_NAVN = "Stavanger"

OUTPUT_ROOT = Path("kundeaviser")
MIN_PDF_SIZE_BYTES = 100_000  # ~100 KB — enkel sanity-sjekk av nedlastet fil
REQUEST_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; KundeavisBot/1.0; privat bruk)"
HEADERS = {"User-Agent": USER_AGENT}


@dataclass
class Chain:
    key: str                    # brukt i filnavn, f.eks. "rema1000"
    display_name: str           # f.eks. "REMA 1000"
    mattilbud_url: str          # primærkilde: kjedens side på mattilbud.no
    fallback_url: Optional[str] = None  # kjedens egen offisielle side, brukt kun hvis mattilbud.no feiler helt


# Primærkilde for alle kjeder: mattilbud.no (kjører på Tjek/tidl. ShopGun
# sin kundeavis-plattform). URL-ene under er bekreftet å eksistere (funnet
# via websøk, ikke gjettet) — se strategy_mattilbud() for hvordan siden
# faktisk hentes.
CHAINS = [
    Chain(
        key="rema1000",
        display_name="REMA 1000",
        mattilbud_url="https://mattilbud.no/kundeaviser/rema-1000-no",
        fallback_url="https://rema.no/kundeavis",
    ),
    Chain(
        key="kiwi",
        display_name="KIWI",
        mattilbud_url="https://mattilbud.no/kundeaviser/kiwi-no",
        fallback_url="https://kiwi.no/",
    ),
    Chain(
        key="coop-extra",
        display_name="Coop Extra",
        mattilbud_url="https://mattilbud.no/kundeaviser/extra-no",
        fallback_url="https://coop.no/",
    ),
    Chain(
        key="meny",
        display_name="Meny",
        mattilbud_url="https://mattilbud.no/kundeaviser/meny-no",
        fallback_url="https://meny.no/",
    ),
    Chain(
        key="spar",
        display_name="Spar",
        mattilbud_url="https://mattilbud.no/kundeaviser/spar-no",
        fallback_url="https://spar.no/",
    ),
    Chain(
        key="bunnpris",
        display_name="Bunnpris",
        mattilbud_url="https://mattilbud.no/kundeaviser/bunnpris-no",
        fallback_url="https://bunnpris.no/",
    ),
]

# ---------------------------------------------------------------------------
# HJELPEFUNKSJONER
# ---------------------------------------------------------------------------

def get_week_folder():
    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    folder = OUTPUT_ROOT / f"{iso_year}-uke{iso_week:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder, f"uke{iso_week:02d}", monday.isoformat(), sunday.isoformat()


def validate_pdf(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < MIN_PDF_SIZE_BYTES:
        return False
    with open(path, "rb") as f:
        header = f.read(5)
    return header == b"%PDF-"


def download_binary(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return validate_pdf(dest)
    except requests.RequestException as e:
        logging.warning(f"Nedlasting feilet ({url}): {e}")
        return False


def find_pdf_link_in_html(html: str, base_url: str) -> Optional[str]:
    """Enkel leting etter en .pdf-lenke som ser ut som en kundeavis, både i
    <a href> og i rå PDF-URLer skjult i JS/JSON-blokker på siden."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = [a["href"] for a in soup.find_all("a", href=True)
                  if re.search(r"\.pdf($|\?)", a["href"], re.IGNORECASE)]
    candidates += re.findall(r'https?://[^\s"\']+\.pdf', html)
    if not candidates:
        return None
    prioritized = [c for c in candidates if re.search(r"kundeavis|tilbud", c, re.IGNORECASE)]
    chosen = prioritized[0] if prioritized else candidates[0]
    if chosen.startswith("//"):
        chosen = "https:" + chosen
    elif chosen.startswith("/"):
        chosen = urljoin(base_url, chosen)
    return chosen


def find_page_image_urls_in_html(html: str) -> list:
    """Best-effort-forsøk på å finne en serie sidebilder for en kundeavis
    fra en "digital avis"-plattform (f.eks. Tjek/tidl. ShopGun, som ligger
    bak mattilbud.no). Slike plattformer legger ofte katalogens sidebilder
    som en liste med bilde-URLer i en innebygd JSON-blokk på siden.

    Dette er en GENERISK heuristikk — IKKE verifisert mot den faktiske
    JSON-strukturen til noen bestemt plattform (ingen nettverkstilgang til
    mattilbud.no i miljøet dette ble skrevet i). Den leter etter alle
    bilde-URLer i HTML-en, grupperer dem etter "mønster" (samme URL med
    tall erstattet av #), og returnerer den største gruppen — siden
    sidebilder typisk deler samme sti/CDN og bare varierer i et tall
    (side- eller bilde-ID). Hvis dette ikke finner riktige bilder på en
    gitt side, må logikken justeres etter å ha inspisert siden i
    nettleseren (F12 → Network/Sources)."""
    urls = re.findall(r'https?://[^\s"\'\\]+\.(?:jpe?g|png|webp)(?:\?[^\s"\'\\]*)?', html, re.IGNORECASE)
    if not urls:
        return []

    grupper = {}
    for url in urls:
        monster = re.sub(r"\d+", "#", url)
        grupper.setdefault(monster, [])
        if url not in grupper[monster]:
            grupper[monster].append(url)

    storste_gruppe = max(grupper.values(), key=len)
    return storste_gruppe if len(storste_gruppe) >= 2 else []


def images_to_pdf(image_urls: list, dest: Path) -> bool:
    """Laster ned en liste med bilde-URLer i rekkefølge og slår dem sammen
    til én PDF (ett bilde per side). Brukes når kundeavisen leveres som en
    serie sidebilder i stedet for én ferdig PDF-fil."""
    bilder = []
    url = None
    try:
        for url in image_urls:
            r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            bilder.append(Image.open(io.BytesIO(r.content)).convert("RGB"))
    except Exception as e:
        logging.warning(f"Kunne ikke laste ned sidebilde ({url}): {e}")
        return False

    if not bilder:
        return False
    try:
        bilder[0].save(str(dest), save_all=True, append_images=bilder[1:])
    except Exception as e:
        logging.warning(f"Kunne ikke sette sammen sidebilder til PDF: {e}")
        return False
    return validate_pdf(dest)


def dismiss_cookie_banner(page) -> bool:
    """Prøver å lukke cookie-samtykke-banneret på flere måter, og logger
    tydelig hva som skjer i stedet for å feile stille."""
    page.wait_for_timeout(1500)  # gi banneret tid til å rekke å tegnes opp

    attempts = [
        lambda: page.get_by_role("dialog").get_by_role("button", name="Godta", exact=False),
        lambda: page.get_by_role("button", name="Godta", exact=False),
        lambda: page.get_by_role("button", name="Kun nødvendige", exact=False),
        lambda: page.locator("button:has-text('Godta')"),
        lambda: page.locator("#onetrust-accept-btn-handler"),
        lambda: page.locator("#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"),
    ]

    for i, get_locator in enumerate(attempts):
        try:
            locator = get_locator().first
            if locator.count() == 0:
                continue
            locator.wait_for(state="visible", timeout=3000)
            locator.click(timeout=3000, force=True)
            page.wait_for_timeout(1000)
            logging.info(f"Cookie-banner lukket med forsøk #{i}")
            return True
        except Exception as e:
            logging.info(f"Forsøk #{i} feilet: {e}")
            continue

    # Siste utvei: fjern selve dialog-elementet direkte fra siden med JavaScript,
    # uansett hvilken knappetekst det bruker
    try:
        page.evaluate("document.querySelectorAll('[role=\"dialog\"]').forEach(el => el.remove())")
        page.wait_for_timeout(500)
        logging.info("Fjernet dialog-element direkte via JavaScript (brute force).")
        return True
    except Exception as e:
        logging.warning(f"Klarte ikke å fjerne banneret i det hele tatt: {e}")
        return False


def _chromium_launch_kwargs() -> dict:
    """Playwrights normale `playwright install chromium` legger nettleseren
    under PLAYWRIGHT_BROWSERS_PATH med et revisjonsnummer som må matche
    den installerte playwright-pakken nøyaktig. I enkelte miljøer (f.eks.
    sandkasser med begrenset nettverkstilgang) ligger det i stedet en
    forhåndsinstallert Chromium på en fast sti under samme mappe, med en
    `chromium`-symlink som peker på den faktiske kjørbare filen. Bruk den
    hvis den finnes, ellers la Playwright bruke sin vanlige oppdagelse."""
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if browsers_path:
        candidate = Path(browsers_path) / "chromium"
        if candidate.exists():
            return {"executable_path": str(candidate)}
    return {}


# ---------------------------------------------------------------------------
# NEDLASTINGSSTRATEGIER
# ---------------------------------------------------------------------------

def strategy_browser_print(url: str, display_name: str, dest: Path) -> bool:
    """Universalstrategi: rendre en side i en headless nettleser og eksporter
    til PDF. Krever ikke at vi finner en spesifikk PDF-ressurs, men fanger
    ikke nødvendigvis alle sidene i en bla-i-avis-widget (se begrensning
    øverst i filen)."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**_chromium_launch_kwargs())
            page = browser.new_page()
            page.goto(url, timeout=30_000, wait_until="networkidle")
            dismiss_cookie_banner(page)
            page.pdf(path=str(dest), format="A4", print_background=True)
            browser.close()
        return validate_pdf(dest)
    except PlaywrightTimeout as e:
        logging.warning(f"[{display_name}] Playwright timeout: {e}")
        return False
    except Exception as e:
        logging.warning(f"[{display_name}] Browser-print feilet: {e}")
        return False


def strategy_mattilbud(chain: Chain, dest: Path) -> bool:
    """Henter kundeavisen fra mattilbud.no — primærkilden for alle kjeder.
    mattilbud.no (og søsterplattformen etilbudsavis.no) kjører på Tjek
    (tidl. ShopGun) sin kundeavis-plattform, som viser hver kjedes
    kundeavis på en fast URL (f.eks. mattilbud.no/kundeaviser/kiwi-no).
    URL-ene i chain.mattilbud_url er bekreftet å eksistere (funnet via
    websøk). mattilbud.no er en JS-tung SPA — diagnostisert mot ekte side
    (aug. 2026): rett etter "networkidle" var page.content() bare ~500
    tegn (en tom skjelett-side), altså ikke ferdig rendret ennå. Derfor en
    ekstra fast ventetid før vi leser innholdet, i tillegg til
    "networkidle".

    Prøver i rekkefølge: (1) en direkte PDF-lenke på siden, (2) en serie
    sidebilder funnet av find_page_image_urls_in_html() satt sammen til én
    PDF — dette er den interessante biten, siden det kan fange ALLE
    sidene i avisen i stedet for bare gjeldende visning, (3) vanlig
    browser-print av siden som siste utvei (kun gjeldende visning)."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**_chromium_launch_kwargs())
            page = browser.new_page()
            page.goto(chain.mattilbud_url, timeout=30_000, wait_until="networkidle")
            dismiss_cookie_banner(page)
            page.wait_for_timeout(4000)  # la SPA-en rekke å rendre innholdet
            html = page.content()
            browser.close()
    except Exception as e:
        logging.warning(f"[{chain.display_name}] Klarte ikke å laste mattilbud.no: {e}")
        return False

    pdf_url = find_pdf_link_in_html(html, chain.mattilbud_url)
    if pdf_url:
        logging.info(f"[{chain.display_name}] Fant PDF-lenke på mattilbud.no: {pdf_url}")
        if download_binary(pdf_url, dest):
            return True

    bilde_urler = find_page_image_urls_in_html(html)
    if bilde_urler:
        logging.info(f"[{chain.display_name}] Fant {len(bilde_urler)} sidebilder på mattilbud.no — setter sammen til PDF.")
        if images_to_pdf(bilde_urler, dest):
            return True
        logging.warning(f"[{chain.display_name}] Klarte ikke å sette sammen sidebildene til PDF.")

    logging.info(f"[{chain.display_name}] Fant verken PDF-lenke eller sidebilder på mattilbud.no — faller tilbake til browser-print (kun gjeldende visning).")
    return strategy_browser_print(chain.mattilbud_url, chain.display_name, dest)


def strategy_fallback(chain: Chain, dest: Path) -> bool:
    """Siste utvei hvis mattilbud.no feiler helt: printer kjedens egen
    offisielle side direkte."""
    if not chain.fallback_url:
        return False
    logging.info(f"[{chain.display_name}] Prøver fallback-kilde (kjedens egen side): {chain.fallback_url}")
    return strategy_browser_print(chain.fallback_url, chain.display_name, dest)


# ---------------------------------------------------------------------------
# HOVEDLOGIKK
# ---------------------------------------------------------------------------

def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    folder, week_label, start_date, end_date = get_week_folder()
    status = {
        "uke": week_label,
        "region": REGION_NAVN,
        "kjort": date.today().isoformat(),
        "resultater": {},
    }

    for chain in CHAINS:
        dest = folder / f"{chain.key}_{REGION_NAVN.lower()}_{week_label}_{start_date}_{end_date}.pdf"
        logging.info(f"=== {chain.display_name} ===")

        success = strategy_mattilbud(chain, dest)
        if not success:
            success = strategy_fallback(chain, dest)

        if success:
            status["resultater"][chain.key] = {"status": "ok", "fil": str(dest)}
            logging.info(f"[{chain.display_name}] OK -> {dest}")
        else:
            status["resultater"][chain.key] = {"status": "feilet"}
            logging.error(f"[{chain.display_name}] Klarte ikke å hente kundeavis (heller ikke fallback).")

    (folder / "_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print_report(status)


def print_report(status: dict):
    ok = [k for k, v in status["resultater"].items() if v["status"] == "ok"]
    feilet = [k for k, v in status["resultater"].items() if v["status"] == "feilet"]
    print(f"\nKUNDEAVIS-RAPPORT – {status['uke']} ({status['region']})")
    print(f"Kjørt: {status['kjort']}\n")
    print(f"OK ({len(ok)}): {', '.join(ok) if ok else '-'}")
    print(f"Feilet ({len(feilet)}): {', '.join(feilet) if feilet else '-'}")


if __name__ == "__main__":
    run()

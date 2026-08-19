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
1. Flere kjeder viser kundeavisen i en interaktiv "bla-i-avis"-viser
   (Tjek/ShopGun-teknologi). Slike visere laster ofte sidene dynamisk etter
   hvert som man blar, som en presentasjon — ikke som ett langt dokument.
   "browser_print"-strategien under (skriv siden ut til PDF via headless
   nettleser) fanger da ofte KUN gjeldende visning/side, ikke nødvendigvis
   alle sidene i avisen. For å fange ALLE sidene trengs en mer avansert
   løsning som blar side for side og tar skjermbilde av hver, for så å slå
   dem sammen til én PDF. Si fra hvis du vil ha hjelp til å bygge den biten.
2. Selectorene i "postnummer_form"/"butikksok_form"-strategien (søkefelt,
   butikk-liste) er IKKE verifisert og må trolig justeres.
3. dismiss_cookie_banner() prøver flere kjente mønstre (dialog-rolle +
   "Godta"-knapp, OneTrust, Cookiebot, generisk tekstsøk) og logger tydelig
   hvilket forsøk som lyktes eller feilet. Som siste utvei fjernes
   [role="dialog"]-elementer direkte via JavaScript. Den er testet mot
   syntetiske testsider som etterligner disse banner-mønstrene, men IKKE
   mot de faktiske kjede-nettstedene (se nettverksbegrensning under).
   Treffer den ikke riktig knapp på en gitt side, må selectoren/teksten
   legges til i listen etter å ha inspisert banneret i nettleseren
   (F12 → Inspiser).
4. Respekter robots.txt og bruksvilkår for hver side. Dette scriptet gjør
   kun ett forsøk per kjede per kjøring og bør ikke kjøres oftere enn
   nødvendig (default: ukentlig).

INSTALLASJON
-------------
    pip install requests beautifulsoup4 playwright
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
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ---------------------------------------------------------------------------
# KONFIG
# ---------------------------------------------------------------------------

REGION_NAVN = "Stavanger"
POSTNUMMER = "4027"  # <-- juster til ditt nøyaktige postnummer i Stavanger

OUTPUT_ROOT = Path("kundeaviser")
MIN_PDF_SIZE_BYTES = 100_000  # ~100 KB — enkel sanity-sjekk av nedlastet fil
REQUEST_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; KundeavisBot/1.0; privat bruk)"
HEADERS = {"User-Agent": USER_AGENT}


@dataclass
class Chain:
    key: str                    # brukt i filnavn, f.eks. "rema1000"
    display_name: str           # f.eks. "REMA 1000"
    landing_url: str            # siden vi starter på
    mode: str                   # "direct_pdf_scan" | "browser_print" | "postnummer_form" | "butikksok_form"
    fallback_url: Optional[str] = None  # tredjeparts-kilde hvis primær feiler
    search_query: Optional[str] = None  # brukt av "butikksok_form" — by/butikknavn å søke etter


CHAINS = [
    Chain(
        key="rema1000",
        display_name="REMA 1000",
        landing_url="https://rema.no/kundeavis",  # bekreftet URL (aug. 2026)
        mode="postnummer_form",
        fallback_url="https://www.tilbudsuken.no/kundeavis/Dagligvarer/Rema%201000",
    ),
    Chain(
        key="kiwi",
        display_name="KIWI",
        landing_url="https://kiwi.no/",  # bekreftet domene — TODO/VERIFISER riktig understi (tilbud/kundeavis)
        mode="direct_pdf_scan",  # KIWI har historisk publisert direkte PDF-lenker (kiwi.no/globalassets/kundeavis-...)
        fallback_url="https://www.tilbudsuken.no/kundeavis/Dagligvarer/Kiwi",
    ),
    Chain(
        key="coop-extra",
        display_name="Coop Extra",
        landing_url="https://coop.no/",  # TODO/VERIFISER riktig understi for kundeavis
        mode="browser_print",
        fallback_url="https://www.tilbudsuken.no/kundeavis/Dagligvarer/Coop%20Extra",
    ),
    Chain(
        key="meny",
        display_name="Meny",
        landing_url="https://meny.no/",  # TODO/VERIFISER
        mode="browser_print",
        fallback_url="https://www.tilbudsuken.no/kundeavis/Dagligvarer/Meny",
    ),
    Chain(
        key="spar",
        display_name="Spar",
        landing_url="https://spar.no/",  # TODO/VERIFISER
        mode="browser_print",
        fallback_url="https://www.tilbudsuken.no/kundeavis/Dagligvarer/Spar",
    ),
    Chain(
        key="bunnpris",
        display_name="Bunnpris",
        landing_url="https://bunnpris.no/",  # TODO/VERIFISER
        mode="butikksok_form",  # krever by/butikknavn før riktig kundeavis vises
        fallback_url="https://www.tilbudsuken.no/kundeavis/Dagligvarer/Bunnpris",
        search_query=REGION_NAVN,  # "Stavanger"
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

def strategy_direct_pdf_scan(chain: Chain, dest: Path) -> bool:
    try:
        r = requests.get(chain.landing_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        logging.warning(f"[{chain.display_name}] Klarte ikke å hente landingsside: {e}")
        return strategy_browser_print(chain, dest)

    pdf_url = find_pdf_link_in_html(r.text, chain.landing_url)
    if not pdf_url:
        logging.info(f"[{chain.display_name}] Fant ingen direkte PDF-lenke — prøver browser-print i stedet.")
        return strategy_browser_print(chain, dest)

    logging.info(f"[{chain.display_name}] Fant PDF-lenke: {pdf_url}")
    return download_binary(pdf_url, dest)


def strategy_browser_print(chain: Chain, dest: Path) -> bool:
    """Universalstrategi: rendre siden i en headless nettleser og eksporter
    til PDF. Krever ikke at vi finner en spesifikk PDF-ressurs, men fanger
    ikke nødvendigvis alle sidene i en bla-i-avis-widget (se begrensning
    øverst i filen)."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**_chromium_launch_kwargs())
            page = browser.new_page()
            page.goto(chain.landing_url, timeout=30_000, wait_until="networkidle")
            dismiss_cookie_banner(page)
            page.pdf(path=str(dest), format="A4", print_background=True)
            browser.close()
        return validate_pdf(dest)
    except PlaywrightTimeout as e:
        logging.warning(f"[{chain.display_name}] Playwright timeout: {e}")
        return False
    except Exception as e:
        logging.warning(f"[{chain.display_name}] Browser-print feilet: {e}")
        return False


def strategy_sok_og_velg_butikk(chain: Chain, dest: Path) -> bool:
    """For kjeder (som REMA 1000 og Bunnpris) der man må søke opp butikk —
    via postnummer eller via by-/butikknavn — før riktig lokal kundeavis
    vises. Søketeksten er chain.search_query hvis satt (f.eks. "Stavanger"
    for Bunnpris), ellers POSTNUMMER som standard (REMA 1000). Selectorene
    under er IKKE verifisert og MÅ justeres etter å ha inspisert siden i
    nettleseren (F12 → Inspiser)."""
    query = chain.search_query or POSTNUMMER
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**_chromium_launch_kwargs())
            page = browser.new_page()
            page.goto(chain.landing_url, timeout=30_000, wait_until="networkidle")
            dismiss_cookie_banner(page)

            # TODO/VERIFISER: bytt ut med faktisk selector for søkefeltet
            SOK_FELT_SELECTOR = (
                "input[type='search'], "
                "input[placeholder*='postnummer' i], "
                "input[placeholder*='butikk' i], "
                "input[placeholder*='sted' i], "
                "input[placeholder*='by' i]"
            )
            page.fill(SOK_FELT_SELECTOR, query)
            page.keyboard.press("Enter")
            page.wait_for_timeout(2000)

            # TODO/VERIFISER: klikk første butikk-treff i resultatlisten
            FORSTE_TREFF_SELECTOR = "[data-testid='store-result'], .store-list-item"
            if page.locator(FORSTE_TREFF_SELECTOR).count() > 0:
                page.locator(FORSTE_TREFF_SELECTOR).first.click()
                page.wait_for_timeout(2000)

            page.pdf(path=str(dest), format="A4", print_background=True)
            browser.close()
        return validate_pdf(dest)
    except Exception as e:
        logging.warning(f"[{chain.display_name}] Butikksøk-flyt feilet ({query!r}): {e}")
        return False


def strategy_fallback(chain: Chain, dest: Path) -> bool:
    if not chain.fallback_url:
        return False
    logging.info(f"[{chain.display_name}] Prøver fallback-kilde: {chain.fallback_url}")
    temp_chain = Chain(chain.key, chain.display_name, chain.fallback_url, "browser_print")
    return strategy_browser_print(temp_chain, dest)


STRATEGIES = {
    "direct_pdf_scan": strategy_direct_pdf_scan,
    "browser_print": strategy_browser_print,
    "postnummer_form": strategy_sok_og_velg_butikk,
    "butikksok_form": strategy_sok_og_velg_butikk,
}

# ---------------------------------------------------------------------------
# HOVEDLOGIKK
# ---------------------------------------------------------------------------

def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    folder, week_label, start_date, end_date = get_week_folder()
    status = {
        "uke": week_label,
        "region": REGION_NAVN,
        "postnummer": POSTNUMMER,
        "kjort": date.today().isoformat(),
        "resultater": {},
    }

    for chain in CHAINS:
        dest = folder / f"{chain.key}_{REGION_NAVN.lower()}_{week_label}_{start_date}_{end_date}.pdf"
        logging.info(f"=== {chain.display_name} ===")

        success = STRATEGIES[chain.mode](chain, dest)
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
    print(f"\nKUNDEAVIS-RAPPORT – {status['uke']} ({status['region']}, postnr {status['postnummer']})")
    print(f"Kjørt: {status['kjort']}\n")
    print(f"OK ({len(ok)}): {', '.join(ok) if ok else '-'}")
    print(f"Feilet ({len(feilet)}): {', '.join(feilet) if feilet else '-'}")


if __name__ == "__main__":
    run()

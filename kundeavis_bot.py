#!/usr/bin/env python3
"""
kundeavis_bot.py — Henter norske dagligvarekjeders ukentlige kundeaviser som
PDF via Tjek (tidl. ShopGun) sitt offentlige REST-API, og lagrer dem i en
ukesmappe.

VIKTIG — LES FØR BRUK
----------------------
Tidligere versjoner av dette scriptet prøvde å skrape kjedenes egne
nettsider og mattilbud.no med en headless nettleser (Playwright). Det viste
seg upålitelig i praksis: cookie-banner, JS-rendring og manglende
butikkvalg gjorde at "vellykkede" kjøringer ofte ga PDF-er UTEN faktisk
tilbudsinnhold.

Ved diagnose av Bunnpris sin butikkside (aug. 2026) ble det oppdaget at
kjeden bruker Tjek (tidl. ShopGun) sitt offisielle JS-SDK direkte på siden,
med en synlig, offentlig API-nøkkel og en "business/dealer-ID" i HTML-
kildekoden. Tjek-plattformens REST-API (squid-api.tjek.com) viste seg å
være åpent og fungere UTEN egen API-nøkkel. Dealer-ID-ene for de andre 5
kjedene ble funnet/kryssbekreftet via offentlige, ikke-tilknyttede
GitHub-prosjekter (bl.a. holgersetten/ukeshandel.no) som bruker samme API.

Alle 6 dealer-ID-ene under er BEKREFTET fungerende (aug. 2026, kjørt fra
GitHub Actions): hver ga en ekte, aktuell katalog for inneværende uke med
13–31 sider og 100–239 tilbud, og nedlasting av sidebilder ga gyldige
JPEG-filer. Se hent_kundeavis_tjek() for detaljer om hvordan PDF-en bygges.

En 7. kjede, Coop Obs (Mariero), er lagt til på en HELT ANNEN plattform
("iPaper", ikke Tjek) — Coop Obs eksponerer ingen dealer_id eller
REST-API. I stedet leses en signert tilgangs-"policy" ut av den vanlige
HTML-siden for den regionale kundeavisen (kundeavis-obs.coop.no/sorvest/),
og brukes til å bygge sidebilde-URLer direkte. Se hent_kundeavis_ipaper()
for detaljer, inkludert hvordan URL-mønsteret ble funnet.

KJENTE BEGRENSNINGER
---------------------
1. Tjek-APIet gir ÉN kundeavis per dealer_id — det er ikke nødvendigvis
   butikk-/postnummer-spesifikt. For de fleste norske kjeder er den
   ukentlige kundeavisen uansett lik for hele landet eller store regioner,
   men dette scriptet garanterer IKKE at innholdet er 100 % identisk med
   det som henger i en bestemt Stavanger-butikk. REGION_NAVN brukes derfor
   kun som et menneskelesbart navn i mappe-/filnavn, ikke som en reell
   filtrering på Tjek-siden.
2. De fleste kataloger mangler et fungerende pdf_url-felt (returnerer
   404 ved nedlasting) — sannsynligvis fordi de er i Tjek sitt nyere
   "incito"-format (responsivt, ikke fast PDF-layout) i stedet for
   "paged". Scriptet håndterer dette automatisk ved å hente alle
   sidebildene enkeltvis (/catalogs/{id}/pages) og sette dem sammen til
   én PDF med Pillow.
3. Dette er et offentlig, men uoffisielt/udokumentert API uten API-nøkkel.
   Det kan endre seg eller bli stengt uten varsel. Bruk skånsomt (ett
   forsøk per kjede per kjøring, default ukentlig) og ikke for annet enn
   privat bruk.
4. dealer_id for REMA 1000 (faa0Ym) er verifisert å gi norskspråklige
   "Uke NN"-kataloger. En alternativ ID funnet i samme kilde (11deC) ga en
   dansk("Uge NN")-katalog og er IKKE brukt her.
5. iPaper-kjeden (Coop Obs) oppgir ikke gyldighetsdato eller totalt antall
   tilbud noe sted i den statiske HTML-en vi henter — disse feltene settes
   derfor til "?"/None for den kjeden i status/latest.json, i motsetning
   til de 6 Tjek-baserte kjedene.

ROTASJON (sep. 2026)
---------------------
PDF-ene for alle 7 kjeder hentes fortsatt hver kjøring (billig — bare HTTP
+ Pillow). Men den kostbare OCR/vision-ekstraksjonen til strukturert JSON
(se kundeavis.yml sitt "Strukturer tilbud med Claude"-steg) kjøres kun for
PRIMÆR_KJEDER (Coop Obs, Coop Extra, Meny) pluss ÉN av ROTASJON_KJEDER
(REMA 1000, KIWI, Spar, Bunnpris) om gangen, valgt ut fra ISO-ukenummeret —
se aktive_kjeder_denne_uken(). Sett miljøvariabelen FULL_KJORING=true for
å ekstrahere alle 7 kjeder uansett uke (workflow_dispatch-input i
kundeavis.yml). latest.json sitt "aktive_kjeder_denne_uken"-felt sier
nøyaktig hvilke kjeder som ble ekstrahert denne uken.

INSTALLASJON
-------------
    pip install requests Pillow

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
import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

# ---------------------------------------------------------------------------
# KONFIG
# ---------------------------------------------------------------------------

REGION_NAVN = "Stavanger"  # kun et menneskelesbart navn i mappe-/filnavn — se KJENTE BEGRENSNINGER #1

OUTPUT_ROOT = Path("kundeaviser")
LATEST_PDF_DIR = OUTPUT_ROOT / "latest"  # fast sti, overskrives hver uke — se skriv_latest_json()
MIN_PDF_SIZE_BYTES = 100_000  # ~100 KB — enkel sanity-sjekk av ferdig PDF
REQUEST_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
HEADERS = {"User-Agent": USER_AGENT}

TJEK_API_BASE = "https://squid-api.tjek.com/v2"

# iPaper-kjeder (foreløpig kun Coop Obs) henter ikke sidetall noe sted i den
# statiske HTML-en, så vi prøver side 1, 2, 3, ... fortløpende til første
# side som ikke gir et gyldig bilde tilbake. 60 er en romslig øvre grense —
# den regionale Coop Obs-kundeavisen vi har sett hadde ca. 30 sider.
IPAPER_MAKS_SIDER = 60

# Brukes til å bygge en stabil, offentlig rå-URL til hver kjedes nyeste PDF
# (kundeaviser/latest/<key>.pdf), slik at eksterne AI-verktøy (f.eks. et
# Claude Project) kan hente og lese PDF-en direkte via raw.githubusercontent.com
# — Claude sitt web-fetch-verktøy støtter dokumentert HTML og PDF, men ikke
# rå bildefiler, så en kundeavis satt sammen av enkeltbilder (som sider-listen
# i latest.json peker til) kan ikke leses direkte av et slikt verktøy.
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/mk-test-test/Test-for-kj-ring-av-AI-l-ring/main"


@dataclass
class Chain:
    key: str                    # brukt i filnavn, f.eks. "rema1000"
    display_name: str           # f.eks. "REMA 1000"
    platform: str                # "tjek" eller "ipaper" — avgjør hvilken henter som brukes
    dealer_id: Optional[str] = None    # kun "tjek": Tjek/ShopGun sin dealer-ID for kjeden
    ipaper_url: Optional[str] = None   # kun "ipaper": URL til den regionale kundeavis-siden


# Dealer-ID-er bekreftet fungerende mot squid-api.tjek.com (aug. 2026) —
# se modul-docstring for hvordan de ble funnet/verifisert. Coop Obs bruker
# en helt annen plattform (iPaper) og har derfor ingen dealer_id, se
# hent_kundeavis_ipaper().
CHAINS = [
    Chain(key="rema1000", display_name="REMA 1000", platform="tjek", dealer_id="faa0Ym"),
    Chain(key="kiwi", display_name="KIWI", platform="tjek", dealer_id="257bxm"),
    Chain(key="coop-extra", display_name="Coop Extra", platform="tjek", dealer_id="80742m"),
    Chain(key="meny", display_name="Meny", platform="tjek", dealer_id="4333pm"),
    Chain(key="spar", display_name="Spar", platform="tjek", dealer_id="c062vm"),
    Chain(key="bunnpris", display_name="Bunnpris", platform="tjek", dealer_id="5b11sm"),
    Chain(
        key="coop-obs",
        display_name="Coop Obs (Mariero)",
        platform="ipaper",
        ipaper_url="https://kundeavis-obs.coop.no/sorvest/",
    ),
]

# Rotasjon (sep. 2026): kjøringer i uke 35 viste at REMA 1000 og KIWI
# konsekvent bidro minst til bekreftet besparelse når Coop Obs, Coop Extra
# og Meny allerede dekket behovet. PRIMÆR-kjedene hentes/ekstraheres HVER
# uke; ROTASJON-kjedene hentes/ekstraheres kun én om gangen (roterer på
# ISO-ukenummer), med mindre FULL_KJORING er satt (se under). Dette
# reduserer hvor mange kjeder den kostbare OCR/vision-ekstraksjonen
# (kundeavis.yml sitt "Strukturer tilbud med Claude"-steg) må behandle
# hver uke — selve PDF-hentingen her er billig (kun HTTP + Pillow) og gjøres
# fortsatt for alle 7, slik at latest.json/PDF-ene er tilgjengelige for
# manuell sjekk av en hvilken som helst kjede når som helst.
PRIMÆR_KJEDER = {"coop-obs", "coop-extra", "meny"}
ROTASJON_KJEDER = ["rema1000", "kiwi", "spar", "bunnpris"]

# Sett FULL_KJORING=true (miljøvariabel, se workflow_dispatch-input i
# kundeavis.yml) for å ekstrahere alle 7 kjeder denne uken, uavhengig av
# rotasjon — f.eks. ved en spesiell handleuke eller for å teste alle kjeder.
FULL_KJORING = os.environ.get("FULL_KJORING", "").strip().lower() in ("1", "true", "yes")


def aktive_kjeder_denne_uken(iso_week: int) -> set:
    """Returnerer nøklene til kjedene som skal EKSTRAHERES (strukturert
    JSON) denne uken: alle PRIMÆR-kjeder pluss én ROTASJON-kjede valgt ut
    fra ISO-ukenummeret, eller alle 7 hvis FULL_KJORING er satt. PDF-ene
    for alle 7 kjeder hentes uansett (se run()) — rotasjonen gjelder kun
    hvilke kjeder som sendes til den kostbare Claude-ekstraksjonen."""
    if FULL_KJORING:
        return {c.key for c in CHAINS}
    aktiv_rotasjon = ROTASJON_KJEDER[iso_week % len(ROTASJON_KJEDER)]
    return PRIMÆR_KJEDER | {aktiv_rotasjon}

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
    return folder, f"uke{iso_week:02d}", monday.isoformat(), sunday.isoformat(), iso_week


def validate_pdf(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < MIN_PDF_SIZE_BYTES:
        return False
    with open(path, "rb") as f:
        header = f.read(5)
    return header == b"%PDF-"


def hent_siste_katalog(dealer_id: str) -> Optional[dict]:
    """Henter metadata for nyeste kundeavis for en gitt dealer_id via Tjek
    sitt offentlige REST-API. Returnerer katalog-dict (id, label, run_from,
    run_till, page_count, pdf_url, ...) eller None hvis ingen katalog
    finnes eller kallet feiler."""
    url = f"{TJEK_API_BASE}/catalogs?dealer_id={dealer_id}&order_by=-publication_date&offset=0&limit=1"
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        logging.warning(f"Klarte ikke å hente katalogliste for dealer_id={dealer_id}: {e}")
        return None
    return data[0] if data else None


def hent_sidebilder(catalog_id: str) -> list:
    """Henter listen over sidebilde-URLer (700px bredde) for en katalog,
    i siderekkefølge, via Tjek sitt /pages-endepunkt."""
    url = f"{TJEK_API_BASE}/catalogs/{catalog_id}/pages?w=1000"
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        sider = r.json()
    except requests.RequestException as e:
        logging.warning(f"Klarte ikke å hente sidebilder for katalog {catalog_id}: {e}")
        return []
    urler = []
    for side in sider:
        url_ = side.get("view") or side.get("zoom") or side.get("thumb")
        if url_:
            urler.append(url_)
    return urler


def last_ned_pdf_direkte(pdf_url: str, dest: Path) -> bool:
    try:
        r = requests.get(pdf_url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return validate_pdf(dest)
    except requests.RequestException as e:
        logging.warning(f"PDF-nedlasting feilet ({pdf_url}): {e}")
        return False


def images_to_pdf(image_urls: list, dest: Path) -> bool:
    """Laster ned en liste med bilde-URLer i rekkefølge og slår dem sammen
    til én PDF (ett bilde per side)."""
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


# ---------------------------------------------------------------------------
# HOVEDLOGIKK
# ---------------------------------------------------------------------------

def hent_kundeavis(chain: Chain, dest: Path) -> Optional[dict]:
    """Henter nyeste kundeavis for en kjede og lagrer den som PDF på dest.
    Dispatcher til riktig plattform-spesifikk henter basert på
    chain.platform — se hent_kundeavis_tjek() og hent_kundeavis_ipaper()."""
    if chain.platform == "ipaper":
        return hent_kundeavis_ipaper(chain, dest)
    return hent_kundeavis_tjek(chain, dest)


def hent_kundeavis_tjek(chain: Chain, dest: Path) -> Optional[dict]:
    """Henter nyeste kundeavis for en kjede via Tjek sitt offentlige
    REST-API. Prøver først direkte PDF-nedlasting (catalog["pdf_url"]), men
    de fleste kataloger mangler dette feltet eller gir 404 der det finnes
    (trolig "incito"-format uten fast PDF-representasjon). Faller da
    tilbake til å hente alle sidebildene enkeltvis og sette dem sammen til
    én PDF med Pillow — bekreftet å fungere for alle 6 kjeder (aug. 2026).

    Returnerer en info-dict ved suksess (catalog_id, label, run_from,
    run_till, offer_count og — når sidebilde-fallbacken ble brukt —
    Tjek sine egne offentlige bilde-URLer under "sider"), eller None ved
    feil. "sider"-listen brukes bl.a. til å bygge latest.json, se
    skriv_latest_json()."""
    catalog = hent_siste_katalog(chain.dealer_id)
    if not catalog:
        logging.error(f"[{chain.display_name}] Fant ingen kundeavis for dealer_id={chain.dealer_id}")
        return None

    label = catalog.get("label") or "(uten navn)"
    run_from = (catalog.get("run_from") or "?")[:10]
    run_till = (catalog.get("run_till") or "?")[:10]
    page_count = catalog.get("page_count", "?")
    offer_count = catalog.get("offer_count")
    logging.info(
        f"[{chain.display_name}] Fant katalog {catalog.get('id')} — {label!r}, "
        f"gyldig {run_from} til {run_till}, {page_count} sider, "
        f"{offer_count} tilbud"
    )

    info = {
        "catalog_id": catalog.get("id"),
        "label": label,
        "run_from": run_from,
        "run_till": run_till,
        "offer_count": offer_count,
        "sider": [],
    }

    pdf_url = catalog.get("pdf_url")
    if pdf_url and last_ned_pdf_direkte(pdf_url, dest):
        logging.info(f"[{chain.display_name}] Lastet ned direkte PDF fra Tjek-API.")
        return info

    bilde_urler = hent_sidebilder(catalog["id"])
    if not bilde_urler:
        logging.error(f"[{chain.display_name}] Fant ingen sidebilder for katalog {catalog.get('id')}")
        return None

    if images_to_pdf(bilde_urler, dest):
        logging.info(f"[{chain.display_name}] Satte sammen {len(bilde_urler)} sidebilder til PDF.")
        info["sider"] = bilde_urler
        return info

    logging.error(f"[{chain.display_name}] Klarte ikke å sette sammen sidebilder til PDF.")
    return None


IPAPER_STATIC_SETTINGS_RE = re.compile(r"window\.staticSettings\s*=\s*(\{.*?\});", re.DOTALL)


def hent_ipaper_meta(url: str) -> Optional[dict]:
    """Henter en iPaper-kundeavis-side (vanlig HTML, ikke noe REST-API) og
    parser window.staticSettings — et inline <script>-JSON-objekt siden selv
    bruker til å konfigurere sidevisningen. Returnerer dict med bl.a.
    paperId og et "aws"-felt (url/policy) som brukes til å bygge
    sidebilde-URLer, eller None hvis siden ikke svarer eller mangler
    forventet struktur."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        logging.warning(f"Klarte ikke å hente iPaper-side {url}: {e}")
        return None
    m = IPAPER_STATIC_SETTINGS_RE.search(r.text)
    if not m:
        logging.warning(f"Fant ikke window.staticSettings i {url}")
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        logging.warning(f"Kunne ikke parse window.staticSettings fra {url}: {e}")
        return None


def hent_kundeavis_ipaper(chain: Chain, dest: Path) -> Optional[dict]:
    """Henter nyeste kundeavis for en iPaper-basert kjede (foreløpig kun
    Coop Obs). iPaper er en helt annen plattform enn Tjek: ingen dealer_id
    eller REST-API. I stedet henter vi den regionale kundeavis-siden
    (chain.ipaper_url) som vanlig HTML, leser ut en signert tilgangs-
    "policy" fra window.staticSettings.aws (se hent_ipaper_meta()), og
    bruker den til å bygge sidebilde-URLer på mønsteret
    "{aws.url}Pages/{n}/Zoom.jpg?{aws.policy}".

    Dette URL-mønsteret ble reverse-engineert ved å lytte på ALLE
    nettverksresponser i en ekte (headless) nettleser (Playwright) mens
    siden lastet — tre tidligere runder med statisk gjetting av filnavn
    (f.eks. "Pages/1.jpg") ga bare 404, fordi sidetallet faktisk er et eget
    stinivå ("Pages/1/Zoom.jpg"), ikke en del av filnavnet. Mønsteret er
    deretter bekreftet å fungere med et rent HTTP-kall UTEN nettleser
    (aug. 2026) — derfor trengs ikke Playwright i selve produksjonsboten.

    Siden oppgir ikke noe pålitelig sidetall i den statiske HTML-en, så
    sidene hentes fortløpende (1, 2, 3, ...) til første side som ikke gir
    et gyldig bilde tilbake (se IPAPER_MAKS_SIDER).

    Returnerer et info-dict på samme form som hent_kundeavis_tjek(), men
    med run_from/run_till="?" og offer_count=None — iPaper-siden oppgir
    ikke gyldighetsdato eller tilbudstall noe sted."""
    meta = hent_ipaper_meta(chain.ipaper_url)
    if not meta:
        logging.error(f"[{chain.display_name}] Fant ikke iPaper-metadata på {chain.ipaper_url}")
        return None

    aws = meta.get("aws", {})
    base_url = aws.get("url")
    policy = aws.get("policy")
    if not base_url or not policy:
        logging.error(f"[{chain.display_name}] Mangler aws.url/aws.policy i iPaper-metadata")
        return None

    bilder = []
    sider = []
    for n in range(1, IPAPER_MAKS_SIDER + 1):
        side_url = f"{base_url}Pages/{n}/Zoom.jpg?{policy}"
        try:
            r = requests.get(side_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            logging.warning(f"[{chain.display_name}] Feil ved henting av side {n}: {e}")
            break
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
            break
        bilder.append(Image.open(io.BytesIO(r.content)).convert("RGB"))
        sider.append(side_url)

    if not bilder:
        logging.error(f"[{chain.display_name}] Fant ingen sidebilder via iPaper")
        return None

    try:
        bilder[0].save(str(dest), save_all=True, append_images=bilder[1:])
    except Exception as e:
        logging.error(f"[{chain.display_name}] Kunne ikke sette sammen sidebilder til PDF: {e}")
        return None
    if not validate_pdf(dest):
        logging.error(f"[{chain.display_name}] Ferdig PDF besto ikke validering")
        return None

    logging.info(f"[{chain.display_name}] Satte sammen {len(bilder)} sidebilder til PDF (iPaper).")
    return {
        "catalog_id": meta.get("paperId"),
        "label": chain.display_name,
        "run_from": "?",
        "run_till": "?",
        "offer_count": None,
        "sider": sider,
    }


def skriv_latest_json(week_label: str, start_date: str, end_date: str, kjeder_denne_uken: dict, aktive_ekstraksjon: set):
    """Skriver kundeaviser/latest.json — en fast fil (samme filnavn/sti hver
    uke) med metadata og lenker for hver kjede: både Tjek sine egne,
    offentlige sidebilde-URLer ("sider") OG en stabil pdf_url som peker til
    kundeaviser/latest/<key>.pdf i dette repoet (se run()).

    Formålet er å gi en ekstern AI-bot (f.eks. et Claude Project) en STABIL
    URL den kan hente for å alltid få denne ukens tilbud, uten at boten selv
    trenger å konstruere noen URL — noe Claude sitt web-fetch-verktøy ikke
    støtter (den kan kun hente URLer som allerede står i samtalen/tidligere
    verktøyresultater). pdf_url finnes fordi web-fetch-verktøyet dokumentert
    støtter HTML og PDF, men ikke rå bildefiler — sider-listen alene er
    derfor ikke direkte lesbar for slike verktøy. Se .gitignore for
    begrunnelsen for at nettopp kundeaviser/latest/*.pdf (i motsetning til
    de øvrige, tidsstemplede PDF-ene) er et bevisst unntak fra regelen om at
    kjedenes opphavsrettsbeskyttede innhold ikke skal committes til git.

    MERGER med et evt. eksisterende latest.json i stedet for å overskrive
    det helt: PDF-ene for alle 7 kjeder hentes fortsatt hver kjøring (se
    ROTASJON i modul-docstringen — kun den kostbare Claude-ekstraksjonen
    er rotasjonsbegrenset), men en enkelt kjede kan likevel feile en gitt
    uke (nettverksfeil, endret dealer_id, o.l.). Uten merging ville en slik
    forbigående feil slettet kjeden helt fra latest.json i stedet for at
    den forrige, fortsatt gyldige, oppføringen ble stående. Hver kjede får
    et "sist_hentet_uke"-felt som sier hvilken uke dataene faktisk er fra,
    slik at en ekstern AI-bot kan se om en kjedes data er ferske eller
    noen uker gamle. strukturert_url/faste_lavpriser_url peker til faste
    stier som Claude-ekstraksjonssteget i kundeavis.yml skriver til (se
    dette steget for skjemaet)."""
    latest_path = OUTPUT_ROOT / "latest.json"
    eksisterende_kjeder = {}
    if latest_path.exists():
        try:
            eksisterende_kjeder = json.loads(latest_path.read_text(encoding="utf-8")).get("kjeder", {})
        except (json.JSONDecodeError, OSError):
            pass

    kjeder = dict(eksisterende_kjeder)
    kjeder.update(kjeder_denne_uken)

    data = {
        "uke": week_label,
        "region": REGION_NAVN,
        "oppdatert": date.today().isoformat(),
        "gyldig_fra": start_date,
        "gyldig_til": end_date,
        "aktive_kjeder_denne_uken": sorted(aktive_ekstraksjon),
        "strukturert_url": f"{GITHUB_RAW_BASE}/kundeaviser/latest-strukturert.json",
        "faste_lavpriser_url": f"{GITHUB_RAW_BASE}/kundeaviser/latest-faste-lavpriser.json",
        "kjeder": kjeder,
    }
    latest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    LATEST_PDF_DIR.mkdir(parents=True, exist_ok=True)
    folder, week_label, start_date, end_date, iso_week = get_week_folder()
    aktive_ekstraksjon = aktive_kjeder_denne_uken(iso_week)
    logging.info(
        f"Aktive kjeder for ekstraksjon denne uken ({week_label}): "
        f"{', '.join(sorted(aktive_ekstraksjon))}"
        + (" (FULL_KJORING)" if FULL_KJORING else "")
    )

    status = {
        "uke": week_label,
        "region": REGION_NAVN,
        "kjort": date.today().isoformat(),
        "aktive_kjeder_denne_uken": sorted(aktive_ekstraksjon),
        "resultater": {},
    }
    latest_kjeder = {}

    for chain in CHAINS:
        dest = folder / f"{chain.key}_{REGION_NAVN.lower()}_{week_label}_{start_date}_{end_date}.pdf"
        logging.info(f"=== {chain.display_name} ===")

        info = hent_kundeavis(chain, dest)

        if info:
            status["resultater"][chain.key] = {"status": "ok", "fil": str(dest)}
            logging.info(f"[{chain.display_name}] OK -> {dest}")

            latest_pdf = LATEST_PDF_DIR / f"{chain.key}.pdf"
            shutil.copyfile(dest, latest_pdf)

            latest_kjeder[chain.key] = {
                "kjede_navn": chain.display_name,
                "gyldig_fra": info["run_from"],
                "gyldig_til": info["run_till"],
                "tilbud_totalt": info["offer_count"],
                "sider": info["sider"],
                "pdf_url": f"{GITHUB_RAW_BASE}/{latest_pdf.as_posix()}",
                "sist_hentet_uke": week_label,
            }
        else:
            status["resultater"][chain.key] = {"status": "feilet"}
            logging.error(f"[{chain.display_name}] Klarte ikke å hente kundeavis.")

    (folder / "_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    skriv_latest_json(week_label, start_date, end_date, latest_kjeder, aktive_ekstraksjon)
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

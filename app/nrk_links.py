"""Lenker til NRKs kampsider (resultater.nrk.no) pr ferdig kamp.

NRK kjører på NTBs NIFS-data, som har et åpent API (api.nifs.no, ingen nøkkel).
Vi henter VM-stagene (gruppe A–L + sluttspill) for sesongen, lister kampene i
hver stage, og kobler dem til våre kamper på det sorterte kanoniske lagparet –
samme mønster som video-/highlights-koblingen. NRK-URL-en bygges av NIFS-kampens
id og dato:

    https://resultater.nrk.no/fotball/<dato>/1/events/<nifs-id>

Kartet caches (in-memory + best-effort til fil). Det bygges bare på nytt når en
ferdig kamp mangler i cachen (alle gruppekampene er kjent fra start, så etter
første bygg er det vanligvis null kall – sluttspillkampene kommer til etter hvert
som lagene blir avgjort). Ved feil beholdes forrige vellykkede kart.
"""

import datetime
import json
import logging
import os

import httpx

from .teams import canonical

log = logging.getLogger("vm.nrk_links")

BASE = os.environ.get("NIFS_BASE", "https://api.nifs.no")
TOURNAMENT_ID = int(os.environ.get("NIFS_TOURNAMENT_ID", "56"))  # VM
SEASON_YEAR = int(os.environ.get("NIFS_SEASON_YEAR", "2026"))
URL_TEMPLATE = "https://resultater.nrk.no/fotball/{date}/1/events/{id}"
CACHE_PATH = os.environ.get("NRK_LINKS_CACHE", "/data/nrk_links_cache.json")

# pair_key -> [{"id": nifsId, "date": "YYYY-MM-DD"}, ...]. Beholdes mellom oppdateringer.
_map = None
_HEADERS = {"Accept": "application/json", "User-Agent": "vm-grafikk/1.0"}


def pair_key(m):
    """Sortert kanonisk lagpar. m["home"]/m["away"] er allerede kanoniske."""
    return "|".join(sorted([m["home"], m["away"]]))


def _load_cache():
    global _map
    if _map is not None:
        return _map
    _map = {}
    try:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH) as f:
                _map = json.load(f)
            log.info("Lastet %d NRK-lenker fra %s", len(_map), CACHE_PATH)
    except Exception as e:
        log.warning("Klarte ikke lese %s: %s", CACHE_PATH, e)
        _map = {}
    return _map


def _save_cache():
    try:
        os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump(_map, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Klarte ikke skrive %s: %s", CACHE_PATH, e)


def _get(client, path):
    resp = client.get(f"{BASE}{path}")
    resp.raise_for_status()
    return resp.json()


def _rebuild(client):
    """Bygger pair_key -> [{id, date}] fra NIFS for sesongens VM-stages."""
    stages = _get(client, f"/tournaments/{TOURNAMENT_ID}/stages/")
    wc = [s for s in stages if s.get("yearStart") == SEASON_YEAR]
    new = {}
    for s in wc:
        for mm in _get(client, f"/stages/{s['id']}/matches/"):
            h = canonical((mm.get("homeTeam") or {}).get("name") or "")
            a = canonical((mm.get("awayTeam") or {}).get("name") or "")
            if not (h and a):  # sluttspill-plassholdere (1A, 2F …) – hopp over
                continue
            key = "|".join(sorted([h, a]))
            new.setdefault(key, []).append(
                {"id": mm.get("id"), "date": (mm.get("timestamp") or "")[:10]}
            )
    return new


def build_links(finished):
    """Returnerer pair_key -> [{id, date}] for VM-kampene.

    Bygger bare på nytt når en ferdig kamp mangler i cachen."""
    cache = _load_cache()
    if all(pair_key(m) in cache for m in finished):
        return cache

    try:
        with httpx.Client(timeout=30, headers=_HEADERS) as client:
            new = _rebuild(client)
    except httpx.HTTPError as e:
        log.warning("NIFS-oppslag feilet: %s", e)
        return cache

    if new:
        global _map
        _map = new
        log.info("Bygde NRK-lenkekart: %d lagpar", len(new))
        _save_cache()
    return _map


def _date(s):
    try:
        return datetime.date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def url_for(m, links):
    """NRK-URL for kampen, eller None. Velger riktig møte ved gjentatte lagpar."""
    entries = (links or {}).get(pair_key(m))
    if not entries:
        return None
    md = _date(m.get("utc_date"))
    # Nærmeste dato til kampens (NIFS bruker norsk lokaltid, vi har UTC – inntil 1 dag unna).
    best = min(
        entries,
        key=lambda e: abs(((_date(e["date"]) or datetime.date.min) - md).days) if md else 0,
    )
    if not best.get("id"):
        return None
    return URL_TEMPLATE.format(date=best["date"], id=best["id"])

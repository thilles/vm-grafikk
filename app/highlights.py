"""Kamphøydepunkter (mål + kort) fra NRKs NIFS-API (api.nifs.no).

api-sports' gratisplan er ikke brukbar. NRKs resultatsider kjører på NTBs
NIFS-data – det samme åpne, nøkkelfrie API-et som nrk_links.py bruker. Vi
gjenbruker kamp-id-ene nrk_links.build_links allerede resolver, henter hele
kampobjektet (GET /matches/<id>/) og trekker ut hendelsene fra matchEvents.

Hendelser er uforanderlige etter at kampen er ferdig, så de hentes én gang pr
kamp og caches (in-memory + best-effort til fil). En moderat per-oppdatering-
grense begrenser kald oppstart (NIFS er nøkkelfri, men det er høflig).
"""

import datetime
import json
import logging
import os

import httpx

from .teams import canonical, flag, no_name

log = logging.getLogger("vm.highlights")

BASE = os.environ.get("NIFS_BASE", "https://api.nifs.no")
CACHE_PATH = os.environ.get("HIGHLIGHTS_CACHE", "/data/highlights_cache.json")
MAX_MATCHES_PER_REFRESH = int(os.environ.get("HIGHLIGHTS_MAX_PER_REFRESH", "20"))

# NIFS matchEventTypeId (verifisert mot reelle VM-2026-resultat).
T_GOAL = 2       # mål (også straffemål)
T_OWNGOAL = 8    # selvmål
T_YELLOW = 4     # gult kort
T_RED = 3        # rødt kort
T_PEN_AWARD = (9, 10)  # straffe tildelt – samme spiller, rett før målet

_HEADERS = {"Accept": "application/json", "User-Agent": "vm-grafikk/1.0"}
_events = None  # match_key -> {"goals": [...], "cards": [...]}


def match_key(m):
    """Stabil nøkkel pr kamp. m["home"]/m["away"] er allerede kanoniske."""
    date = (m.get("utc_date") or "")[:10]
    return f"{date}|" + "|".join(sorted([m["home"], m["away"]]))


def pair_key(m):
    """Sortert kanonisk lagpar – samme som nrk_links.pair_key."""
    return "|".join(sorted([m["home"], m["away"]]))


def _load_cache():
    global _events
    if _events is not None:
        return _events
    _events = {}
    try:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH) as f:
                _events = json.load(f)
            log.info("Lastet %d cachede kamphøydepunkter fra %s", len(_events), CACHE_PATH)
    except Exception as e:
        log.warning("Klarte ikke lese %s: %s", CACHE_PATH, e)
        _events = {}
    return _events


def _save_cache():
    try:
        os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump(_events, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Klarte ikke skrive %s: %s", CACHE_PATH, e)


def _minute(e):
    """Absolutt kampminutt som streng, f.eks. '27' eller '45+4'."""
    t = e.get("time")
    if t is None:
        return ""
    ot = e.get("overtime")
    return f"{t}" + (f"+{ot}" if ot else "")


def _video(e):
    """Første NRK-klipp-uuid på hendelsen, ellers None."""
    for v in e.get("videos") or []:
        if v.get("url"):
            return v["url"]
    return None


def _minkey(x):
    head = (x.get("minute") or "0").split("+")[0]
    return int(head) if head.isdigit() else 0


def _normalize_events(match_obj):
    """Trekker ut mål og kort fra et NIFS-kampobjekt."""
    evs = match_obj.get("matchEvents") or []

    # Spillere som fikk straffe tildelt (type 9/10) – for å merke målet «(str)».
    # Heuristikk: vi kan ikke knytte straffen til ett bestemt mål, så en spiller
    # som bommer på straffe og senere scorer i åpent spill kan i sjeldne tilfeller
    # få målet feilmerket som straffe. Akseptabelt for en kosmetisk merkelapp.
    pen_players = {
        (e.get("person") or {}).get("name")
        for e in evs
        if e.get("matchEventTypeId") in T_PEN_AWARD and (e.get("person") or {}).get("name")
    }

    goals, cards = [], []
    for e in evs:
        t = e.get("matchEventTypeId")
        team_raw = (e.get("team") or {}).get("name") or ""
        team = canonical(team_raw) or team_raw
        player = (e.get("person") or {}).get("name") or "?"
        minute = _minute(e)

        if t == T_GOAL:
            kind = "penalty" if player in pen_players else "normal"
            goals.append({"team": team, "player": player, "minute": minute,
                          "type": kind, "video": _video(e)})
        elif t == T_OWNGOAL:
            goals.append({"team": team, "player": player, "minute": minute,
                          "type": "own", "video": _video(e)})
        elif t == T_YELLOW:
            cards.append({"team": team, "player": player, "minute": minute, "card": "YELLOW"})
        elif t == T_RED:
            cards.append({"team": team, "player": player, "minute": minute, "card": "RED"})

    goals.sort(key=_minkey)
    cards.sort(key=_minkey)
    return {"goals": goals, "cards": cards}


def _daydiff(a, b):
    """Antall dager mellom to ISO-datoer. Uparsbar dato gir et stort tall slik
    at den taper min()-kåringen i _nifs_id (samme effekt som nrk_links bruker)."""
    try:
        da = datetime.date.fromisoformat((a or "")[:10])
        db = datetime.date.fromisoformat((b or "")[:10])
        return abs((da - db).days)
    except ValueError:
        return 10**6


def _nifs_id(m, links):
    """NIFS-kamp-id for kampen fra nrk_links-kartet, ellers None."""
    entries = (links or {}).get(pair_key(m))
    if not entries:
        return None
    md = (m.get("utc_date") or "")[:10]
    best = min(entries, key=lambda e: _daydiff(e.get("date"), md))
    return best.get("id")


def build_highlights(matches, links):
    """Returnerer {match_key: {goals, cards}} for ferdigspilte kamper.

    Henter bare det som mangler i cachen, og maks MAX_MATCHES_PER_REFRESH kamper
    pr oppdatering. `links` er nrk_links.build_links-kartet (pair_key -> [{id,date}])."""
    cache = _load_cache()
    finished = [m for m in matches if m.get("status") == "FINISHED"]
    missing = [m for m in finished if match_key(m) not in cache]

    if missing:
        fetched = 0
        try:
            with httpx.Client(timeout=30, headers=_HEADERS) as client:
                for m in missing:
                    if fetched >= MAX_MATCHES_PER_REFRESH:
                        log.info("Høydepunkt-grense (%d kamper) nådd, fortsetter neste runde", fetched)
                        break
                    mid = _nifs_id(m, links)
                    if not mid:
                        continue  # ikke resolvet hos NIFS ennå – hopp over
                    resp = client.get(f"{BASE}/matches/{mid}/")
                    resp.raise_for_status()
                    cache[match_key(m)] = _normalize_events(resp.json())
                    fetched += 1
        except httpx.HTTPError as e:
            log.warning("NIFS-oppslag feilet: %s", e)
        if fetched:
            log.info("Hentet kamphøydepunkter for %d kamper fra NIFS", fetched)
            _save_cache()

    return {match_key(m): cache[match_key(m)] for m in finished if match_key(m) in cache}


def view(hl, home_canon=None, away_canon=None):
    """Slår sammen mål+kort til én tidslinje-liste sortert på minutt.

    Hver hendelse tagges med side ('home'/'away') og beriket med flagg/norsk navn.
    Mål beholder video-uuid (None hvis ikke noe klipp)."""
    if not hl:
        return None

    # Tidslinjen er todelt (hjemme venstre / borte høyre). Skulle et kanonisk
    # lagnavn mot formodning ikke matche noen av lagene, plasseres hendelsen til
    # venstre som en trygg standard.
    def side(team):
        if team == home_canon:
            return "home"
        if team == away_canon:
            return "away"
        return "home"

    events = []
    for g in hl.get("goals", []):
        events.append({
            "kind": "goal", "side": side(g["team"]),
            "flag": flag(g["team"]), "team": no_name(g["team"]),
            "player": g["player"], "minute": g["minute"],
            "type": g.get("type", "normal"), "video": g.get("video"),
        })
    for c in hl.get("cards", []):
        events.append({
            "kind": "card", "side": side(c["team"]),
            "flag": flag(c["team"]), "team": no_name(c["team"]),
            "player": c["player"], "minute": c["minute"], "card": c["card"],
        })
    events.sort(key=_minkey)
    if not events:
        return None
    return {"events": events}

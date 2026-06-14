"""Kamphøydepunkter (mål + kort) fra api-sports (v3.football.api-sports.io).

football-data.org gir ikke hendelser på gratisnivået, og api-sports' gratisplan
gir ikke `?league=&season=2026` – men `?date=YYYY-MM-DD` returnerer VM-kampene
(league 1) likevel. Vi bruker derfor:

  1. GET /fixtures?date=…  -> fixture-id pr kamp den datoen (stabilt)
  2. GET /fixtures?id=…    -> events (mål/kort) for én kamp

Hendelser er uforanderlige etter at kampen er ferdig, så de hentes én gang pr
kamp og caches (in-memory + best-effort til fil). En budsjettvakt begrenser
antall API-kall pr oppdatering slik at en kald oppstart ikke sprenger gratis-
kvoten på 100 kall/døgn.

Uten APISPORTS_KEY er modulen en no-op (returnerer tom dict).
"""

import json
import logging
import os
import time

import httpx

from .teams import canonical, flag, no_name

log = logging.getLogger("vm.highlights")

BASE = os.environ.get("APISPORTS_BASE", "https://v3.football.api-sports.io")
WC_LEAGUE_ID = int(os.environ.get("APISPORTS_LEAGUE", "1"))
CACHE_PATH = os.environ.get("HIGHLIGHTS_CACHE", "/data/highlights_cache.json")
MAX_CALLS_PER_REFRESH = int(os.environ.get("APISPORTS_MAX_CALLS_PER_REFRESH", "15"))

# Modul-livssyklus-cache. _events: match_key -> {"goals": [...], "cards": [...]}
_events = None  # lastes lazy fra fil
_date_fixtures = {}  # "YYYY-MM-DD" -> {frozenset({canon, canon}): fixture_id}


def match_key(m):
    """Stabil nøkkel pr kamp – samme på football-data- og api-sports-siden.

    m["home"]/m["away"] er allerede kanoniske (normalisert i football_api)."""
    date = (m.get("utc_date") or "")[:10]
    return f"{date}|" + "|".join(sorted([m["home"], m["away"]]))


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


def _get(client, url, params):
    """GET med enkel 429-backoff. Returnerer JSON-respons eller None ved feil."""
    for _ in range(3):
        resp = client.get(url, params=params)
        if resp.status_code == 429:
            log.warning("api-sports ratelimit (429), venter 5s")
            time.sleep(5)
            continue
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            log.warning("api-sports feil for %s %s: %s", url, params, data["errors"])
            return None
        return data
    return None


def _normalize_events(fixture):
    """Trekker ut mål og kort fra et api-sports fixture-objekt."""
    goals, cards = [], []
    for e in fixture.get("events") or []:
        etype = e.get("type")
        detail = e.get("detail") or ""
        t = e.get("time") or {}
        elapsed, extra = t.get("elapsed"), t.get("extra")
        minute = f"{elapsed}" + (f"+{extra}" if extra else "") if elapsed is not None else ""
        team_raw = (e.get("team") or {}).get("name") or ""
        team = canonical(team_raw) or team_raw
        player = (e.get("player") or {}).get("name") or "?"

        if etype == "Goal" and detail != "Missed Penalty":
            kind = "penalty" if "Penalty" in detail else "own" if "Own Goal" in detail else "normal"
            goals.append({"team": team, "player": player, "minute": minute, "type": kind})
        elif etype == "Card":
            card = "RED" if ("Red" in detail or "Second Yellow" in detail) else "YELLOW"
            cards.append({"team": team, "player": player, "minute": minute, "card": card})

    def _minkey(x):
        head = (x["minute"] or "0").split("+")[0]
        return int(head) if head.isdigit() else 0

    goals.sort(key=_minkey)
    cards.sort(key=_minkey)
    return {"goals": goals, "cards": cards}


def _fixture_ids_for_date(client, date):
    """{frozenset({canon_home, canon_away}): fixture_id} for VM-kamper den datoen."""
    if date in _date_fixtures:
        return _date_fixtures[date]
    idmap = {}
    data = _get(client, f"{BASE}/fixtures", {"date": date})
    for f in (data or {}).get("response") or []:
        if (f.get("league") or {}).get("id") != WC_LEAGUE_ID:
            continue
        teams = f.get("teams") or {}
        home = (teams.get("home") or {}).get("name") or ""
        away = (teams.get("away") or {}).get("name") or ""
        pair = frozenset({canonical(home) or home, canonical(away) or away})
        idmap[pair] = (f.get("fixture") or {}).get("id")
    # Cache bare faktiske treff. Et tomt svar (API-feil, suspendert konto e.l.)
    # caches ikke, slik at neste oppdatering prøver datoen på nytt i stedet for
    # å feste seg på «ingen kamper» til containeren restartes.
    if idmap:
        _date_fixtures[date] = idmap
    return idmap


def build_highlights(matches):
    """Returnerer {match_key: {goals, cards}} for ferdigspilte kamper.

    Henter bare det som mangler i cachen, og maks MAX_CALLS_PER_REFRESH API-kall
    pr oppdatering. No-op (tom dict) uten APISPORTS_KEY."""
    key = os.environ.get("APISPORTS_KEY", "").strip()
    if not key:
        return {}

    cache = _load_cache()
    finished = [m for m in matches if m.get("status") == "FINISHED"]
    missing = [m for m in finished if match_key(m) not in cache]

    if missing:
        calls = 0
        headers = {"x-apisports-key": key}
        try:
            with httpx.Client(timeout=30, headers=headers) as client:
                for m in missing:
                    if calls >= MAX_CALLS_PER_REFRESH:
                        log.info("Budsjettgrense (%d kall) nådd, fortsetter neste runde", calls)
                        break
                    date = (m.get("utc_date") or "")[:10]
                    if date not in _date_fixtures:
                        calls += 1
                    idmap = _fixture_ids_for_date(client, date)
                    fid = idmap.get(frozenset({m["home"], m["away"]}))
                    if not fid:
                        continue  # ikke funnet hos api-sports ennå – hopp over
                    if calls >= MAX_CALLS_PER_REFRESH:
                        break
                    data = _get(client, f"{BASE}/fixtures", {"id": fid})
                    calls += 1
                    resp = (data or {}).get("response") or []
                    if resp:
                        cache[match_key(m)] = _normalize_events(resp[0])
        except httpx.HTTPError as e:
            log.warning("api-sports HTTP-feil: %s", e)
        if calls:
            log.info("Hentet kamphøydepunkter med %d api-sports-kall", calls)
            _save_cache()

    return {match_key(m): cache[match_key(m)] for m in finished if match_key(m) in cache}


def view(hl):
    """Beriker cachede høydepunkter med flagg/norske navn for frontend."""
    if not hl:
        return None
    return {
        "goals": [
            {"flag": flag(g["team"]), "team": no_name(g["team"]),
             "player": g["player"], "minute": g["minute"], "type": g["type"]}
            for g in hl.get("goals", [])
        ],
        "cards": [
            {"flag": flag(c["team"]), "team": no_name(c["team"]),
             "player": c["player"], "minute": c["minute"], "card": c["card"]}
            for c in hl.get("cards", [])
        ],
    }

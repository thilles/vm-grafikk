"""Henter kampdata for VM 2026 fra football-data.org (v4).

Uten FOOTBALL_DATA_TOKEN brukes innebygd demodata slik at appen kan
prøvekjøres før/uten API-nøkkel.
"""
import logging
import os
import time

import httpx

from .teams import canonical

log = logging.getLogger("vm.api")

BASE = "https://api.football-data.org/v4"
COMPETITION = os.environ.get("COMPETITION_CODE", "WC")

# football-data-stadier -> interne stadienavn
STAGE_MAP = {
    "GROUP_STAGE": "GROUP",
    "LAST_32": "R32", "ROUND_OF_32": "R32", "PLAYOFF_ROUND": "R32",
    "LAST_16": "R16", "ROUND_OF_16": "R16",
    "QUARTER_FINALS": "QF", "QUARTER_FINAL": "QF",
    "SEMI_FINALS": "SF", "SEMI_FINAL": "SF",
    "THIRD_PLACE": "THIRD", "PLAY_OFF_FOR_THIRD_PLACE": "THIRD",
    "FINAL": "FINAL",
}


def _normalize_match(m):
    score = m.get("score") or {}
    full = score.get("fullTime") or {}
    reg = score.get("regularTime") or {}
    extra = score.get("extraTime") or {}
    pens = score.get("penalties") or {}
    duration = score.get("duration") or "REGULAR"

    # Mål uten straffekonkurranse
    if duration == "REGULAR" or not reg:
        gh, ga = full.get("home"), full.get("away")
    else:
        gh = (reg.get("home") or 0) + (extra.get("home") or 0)
        ga = (reg.get("away") or 0) + (extra.get("away") or 0)

    group = (m.get("group") or "").replace("GROUP_", "") or None
    home_raw = (m.get("homeTeam") or {}).get("name") or "TBD"
    away_raw = (m.get("awayTeam") or {}).get("name") or "TBD"

    return {
        "id": m.get("id"),
        "utc_date": m.get("utcDate"),
        "status": m.get("status"),  # SCHEDULED/TIMED/IN_PLAY/PAUSED/FINISHED ...
        "stage": STAGE_MAP.get(m.get("stage"), m.get("stage")),
        "group": group,
        "home": canonical(home_raw) or home_raw,
        "away": canonical(away_raw) or away_raw,
        "goals_home": gh,
        "goals_away": ga,
        "pens_home": pens.get("home"),
        "pens_away": pens.get("away"),
        "winner": score.get("winner"),  # HOME_TEAM/AWAY_TEAM/DRAW
        "duration": duration,
    }


def _normalize_scorer(s):
    player = (s.get("player") or {}).get("name") or "?"
    team_raw = (s.get("team") or {}).get("name") or ""
    return {
        "player": player,
        "team": canonical(team_raw) or team_raw,
        "goals": s.get("goals") or 0,
    }


class FootballDataProvider:
    def __init__(self, token):
        self.token = token

    def _get(self, client, url, **kwargs):
        """GET med automatisk throttling basert på API-ets ratelimit-headere."""
        for attempt in range(3):
            resp = client.get(url, **kwargs)
            if resp.status_code == 429:
                wait = min(int(resp.headers.get("Retry-After", "30") or 30), 90)
                log.warning("Ratelimit truffet, venter %ss (%s)", wait, url)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            available = resp.headers.get("X-Requests-Available-Minute")
            if available is not None and available.isdigit() and int(available) <= 1:
                reset = min(int(resp.headers.get("X-RequestCounter-Reset", "60") or 60), 90)
                log.info("Nær ratelimit, venter %ss før neste kall", reset)
                time.sleep(reset)
            return resp
        raise RuntimeError(f"Ga opp etter gjentatte 429-svar fra {url}")

    def fetch(self):
        headers = {"X-Auth-Token": self.token}
        with httpx.Client(timeout=30, headers=headers) as client:
            matches = self._get(client, f"{BASE}/competitions/{COMPETITION}/matches")
            scorers_data = []
            try:
                scorers = self._get(client, f"{BASE}/competitions/{COMPETITION}/scorers",
                                    params={"limit": 20})
                scorers_data = scorers.json().get("scorers", [])
            except (httpx.HTTPError, RuntimeError) as e:
                log.warning("Klarte ikke hente toppscorere: %s", e)
        return {
            "matches": [_normalize_match(m) for m in matches.json().get("matches", [])],
            "scorers": [_normalize_scorer(s) for s in scorers_data],
            "source": "football-data.org",
            "demo": False,
        }


class DemoProvider:
    """Innebygd eksempeldata – brukes når ingen API-nøkkel er satt."""

    def fetch(self):
        def m(date, stage, group, home, away, gh=None, ga=None):
            status = "FINISHED" if gh is not None else "TIMED"
            winner = None
            if gh is not None:
                winner = "HOME_TEAM" if gh > ga else "AWAY_TEAM" if ga > gh else "DRAW"
            return {
                "id": f"demo-{home}-{away}", "utc_date": date, "status": status,
                "stage": stage, "group": group, "home": home, "away": away,
                "goals_home": gh, "goals_away": ga, "pens_home": None, "pens_away": None,
                "winner": winner, "duration": "REGULAR",
            }

        def grp(date, group, home, away, gh=None, ga=None):
            return m(date, "GROUP", group, home, away, gh, ga)

        def ko(date, stage, home, away, gh=None, ga=None):
            return m(date, stage, None, home, away, gh, ga)

        matches = [
            # Gruppekamper
            grp("2026-06-11T19:00:00Z", "A", "Mexico", "South Africa", 2, 1),
            grp("2026-06-11T22:00:00Z", "A", "South Korea", "Czechia", 1, 1),
            grp("2026-06-12T18:00:00Z", "B", "Canada", "Qatar", 3, 0),
            grp("2026-06-12T21:00:00Z", "C", "Morocco", "Brazil", 1, 2),
            grp("2026-06-12T23:00:00Z", "B", "Switzerland", "Bosnia and Herzegovina", 2, 0),
            grp("2026-06-13T16:00:00Z", "C", "Haiti", "Scotland", 1, 0),
            grp("2026-06-13T19:00:00Z", "I", "Norway", "Iraq"),
            grp("2026-06-13T22:00:00Z", "I", "France", "Senegal"),
            grp("2026-06-14T18:00:00Z", "D", "USA", "Paraguay"),
            grp("2026-06-14T21:00:00Z", "E", "Germany", "Curaçao"),
            # Demo-sluttspillkamper for bracket/sunburst-testing
            ko("2026-06-28T18:00:00Z", "R32", "Mexico", "Argentina", 2, 0),
            ko("2026-06-28T21:00:00Z", "R32", "France", "Canada", 3, 1),
            ko("2026-06-29T18:00:00Z", "R32", "Brazil", "Germany", 1, 2),
            ko("2026-06-29T21:00:00Z", "R32", "Spain", "Portugal"),
            ko("2026-06-30T18:00:00Z", "R32", "Norway", "Netherlands"),
            ko("2026-06-30T21:00:00Z", "R32", "England", "USA"),
            ko("2026-07-01T18:00:00Z", "R32", "Uruguay", "Japan"),
            ko("2026-07-01T21:00:00Z", "R32", "Colombia", "Morocco"),
            ko("2026-07-04T18:00:00Z", "R16", "Mexico", "France", 0, 2),
            ko("2026-07-04T21:00:00Z", "R16", "Germany", "Spain"),
            ko("2026-07-05T18:00:00Z", "QF", "France", "Germany"),
        ]
        scorers = [
            {"player": "Kylian Mbappé", "team": "France", "goals": 4},
        ]
        # Demo-høydepunkter (mål/kort) keyet som highlights.match_key: "dato|lagA|lagB"
        highlights = {
            "2026-06-11|Mexico|South Africa": {
                "goals": [
                    {"team": "Mexico", "player": "S. Giménez", "minute": "12", "type": "normal", "video": None},
                    {"team": "South Africa", "player": "L. Mokoena", "minute": "34", "type": "penalty", "video": None},
                    {"team": "Mexico", "player": "H. Lozano", "minute": "78", "type": "normal", "video": None},
                ],
                "cards": [
                    {"team": "South Africa", "player": "T. Mbatha", "minute": "55", "card": "YELLOW"},
                    {"team": "Mexico", "player": "E. Álvarez", "minute": "90+3", "card": "RED"},
                ],
            },
            "2026-06-12|Brazil|Morocco": {
                "goals": [
                    {"team": "Morocco", "player": "Y. En-Nesyri", "minute": "23", "type": "normal", "video": None},
                    {"team": "Brazil", "player": "Vinícius Jr.", "minute": "61", "type": "normal", "video": None},
                    {"team": "Brazil", "player": "Rodrygo", "minute": "88", "type": "normal", "video": None},
                ],
                "cards": [
                    {"team": "Morocco", "player": "S. Amrabat", "minute": "70", "card": "YELLOW"},
                ],
            },
        }
        return {"matches": matches, "scorers": scorers, "source": "demodata",
                "demo": True, "highlights": highlights}


def get_provider():
    token = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
    if token:
        return FootballDataProvider(token)
    log.warning("FOOTBALL_DATA_TOKEN er ikke satt – bruker demodata.")
    return DemoProvider()

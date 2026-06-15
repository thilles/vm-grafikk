"""«Kamp i kampen»: felles klubblag mellom de to landslagene i en kamp.

Slår KG-ens spillerdata (kg.club_rosters) sammen med kampdataene. KG bruker
engelske landslags-labels; de mappes til appens kanoniske lagnavn via
teams.canonical (alias-indeksen håndterer «United States»→«USA» osv.), som er
samme nøkkel kampene allerede er kanonisert på.
"""
from . import kg
from .teams import canonical


def build_index():
    """Bygg klubb-indeks: club_uri → {label, teams: {kanonisk_lag: [{name, value}]}}.

    Tom dict når KG mangler. Bygges pr refresh, men club_rosters() er memoisert,
    så ingen SPARQL kjøres etter første gang – dette er ren in-memory-iterasjon.
    """
    if not kg.available():
        return {}
    index = {}
    for r in kg.club_rosters():
        canon = canonical(r["team_label"])
        if not canon:
            continue  # KG-lag som ikke finnes i appens lagtabell
        club = index.setdefault(r["club"], {"label": r["club_label"], "teams": {}})
        club["teams"].setdefault(canon, []).append(
            {"name": r["player_name"], "value": r["value"]}
        )
    return index


def for_match(m, index):
    """Liste av felles klubblag for de to lagene i kampen, ellers None.

    m["home"]/m["away"] er kanoniske lagnavn (samme nøkkel som indeksen)."""
    if not index:
        return None
    home, away = m["home"], m["away"]
    clubs = []
    for club in index.values():
        teams = club["teams"]
        if home in teams and away in teams:
            clubs.append(
                {"club": club["label"], "home": teams[home], "away": teams[away]}
            )
    clubs.sort(key=lambda c: c["club"])
    return clubs or None

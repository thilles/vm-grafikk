"""Poengberegning: utleder fasit fra kampdata og sammenligner med tippesvar.

Poengregler (antakelser der skjemaet ikke spesifiserer, se README):
- Grupperekkefølge: 1p per lag på riktig plass (maks 4p per gruppe)
- Kampresultat: 4p for eksakt resultat
- Semifinalister: 4p per riktig lag
- Alle øvrige spørsmål: full pott ved riktig svar

Status per spørsmål: pending (ikke avgjort), provisional (foreløpig), final.
"""

import json
import logging
import os

from .teams import TEAMS, canonical, group_of, is_african, no_name, norm, teams_in_group

log = logging.getLogger("vm.scoring")

STAGE_ORDER = ["GROUP", "R32", "R16", "QF", "SF", "THIRD", "FINAL"]
STAGE_SIZE = {"R32": 32, "R16": 16, "QF": 8, "SF": 4, "FINAL": 2}
NORGE_UT_BY_STAGE = {
    "GROUP": "Gruppespill",
    "R32": "16-delsfinale",
    "R16": "8-delsfinale",
    "QF": "Kvartfinale",
    "SF": "Semifinale",
}
QF_BUCKETS = ["0-5", "6-10", "11-15", "16-20", "21-25", "26-30"]
SCORER_OPTIONS = [
    "Mbappe",
    "Kane",
    "Haaland",
    "Messi",
    "Ronaldo",
    "Yamal",
    "Oyarzabal",
    "Vinicius",
]


def load_fasit():
    path = os.environ.get("FASIT_JSON", "/data/fasit.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            log.error("Klarte ikke lese %s: %s", path, e)
    return {}


def compute_group_tables(matches):
    """Gruppetabeller beregnet fra ferdigspilte gruppekamper."""
    tables = {}
    for letter in "ABCDEFGHIJKL":
        rows = {
            t: {
                "team": t,
                "played": 0,
                "w": 0,
                "d": 0,
                "l": 0,
                "gf": 0,
                "ga": 0,
                "pts": 0,
            }
            for t in teams_in_group(letter)
        }
        for m in matches:
            if (
                m["stage"] != "GROUP"
                or m["group"] != letter
                or m["status"] != "FINISHED"
            ):
                continue
            h, a = m["home"], m["away"]
            if h not in rows or a not in rows:
                continue
            gh, ga = m["goals_home"] or 0, m["goals_away"] or 0
            rows[h]["played"] += 1
            rows[a]["played"] += 1
            rows[h]["gf"] += gh
            rows[h]["ga"] += ga
            rows[a]["gf"] += ga
            rows[a]["ga"] += gh
            if gh > ga:
                rows[h]["w"] += 1
                rows[h]["pts"] += 3
                rows[a]["l"] += 1
            elif ga > gh:
                rows[a]["w"] += 1
                rows[a]["pts"] += 3
                rows[h]["l"] += 1
            else:
                rows[h]["d"] += 1
                rows[a]["d"] += 1
                rows[h]["pts"] += 1
                rows[a]["pts"] += 1
        table = sorted(
            rows.values(),
            key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"], r["team"]),
        )
        for i, r in enumerate(table):
            r["pos"] = i + 1
            r["gd"] = r["gf"] - r["ga"]
        tables[letter] = table
    return tables


def compute_thirds_ranking(tables):
    """
    Rangerer de 12 gruppetreerne etter FIFAs kriterier:
    1. Poeng (høyest best)
    2. Målforskjell (høyest best)
    3. Scorede mål (flest best)
    4. Fair-play er ikke implementert (kortdata mangler i free-tier API)
    5. Alfabetisk lagnavn som siste tiebreaker
       (loddtrekning er ikke mulig å simulere)

    De 8 beste treerne av 12 går videre til 16-delsfinalen (R32).

    Merk: FIFA 2026 har ikke offentliggjort matrisen for nøyaktig hvilken
    bracket-plass de viderekommende treerne havner i basert på gruppekombi-
    nasjon. Koblingen er stubbet og kan implementeres når matrisen publiseres.

    Returnerer liste med alle 12 treerne; 'advances' er True for rank 1–8.
    """
    thirds = []
    for letter in sorted(tables.keys()):
        table = tables[letter]
        if len(table) >= 3:
            r = dict(table[2])  # 3. plass (0-indeksert: indeks 2)
            r["group"] = letter
            thirds.append(r)

    # Sortering: poeng → målforskjell → scorede mål → lagnavn (alfabetisk tiebreaker)
    thirds.sort(
        key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"], r["team"])
    )

    for i, r in enumerate(thirds):
        r["rank"] = i + 1
        r["advances"] = i < 8  # De 8 beste treerne går videre til R32

    return thirds


def _group_complete(matches, letter):
    finished = [
        m
        for m in matches
        if m["stage"] == "GROUP" and m["group"] == letter and m["status"] == "FINISHED"
    ]
    return len(finished) >= 6


def _stage_teams(matches, stage):
    """Kjente (ekte) lag i et sluttspillsstadium."""
    teams = set()
    for m in matches:
        if m["stage"] != stage:
            continue
        for t in (m["home"], m["away"]):
            if t in TEAMS:
                teams.add(t)
    return teams


def _stage_known(matches, stage):
    return len(_stage_teams(matches, stage)) >= STAGE_SIZE.get(stage, 99)


def _team_elimination(matches, team):
    """(status, stadium-laget-røk-ut-i | 'WINNER') for et lag."""
    final = next((m for m in matches if m["stage"] == "FINAL"), None)
    if (
        final
        and final["status"] == "FINISHED"
        and team in (final["home"], final["away"])
    ):
        won = (final["winner"] == "HOME_TEAM" and final["home"] == team) or (
            final["winner"] == "AWAY_TEAM" and final["away"] == team
        )
        return "final", "WINNER" if won else "FINAL"

    # Tapte laget en ferdigspilt sluttspillskamp?
    for stage in ["SF", "QF", "R16", "R32"]:
        for m in matches:
            if (
                m["stage"] != stage
                or m["status"] != "FINISHED"
                or team not in (m["home"], m["away"])
            ):
                continue
            won = (m["winner"] == "HOME_TEAM" and m["home"] == team) or (
                m["winner"] == "AWAY_TEAM" and m["away"] == team
            )
            if not won:
                return "final", stage

    # Røk laget ut i gruppespillet? Krever at hele R32-oppsettet er kjent.
    letter = group_of(team)
    if letter and _group_complete(matches, letter) and _stage_known(matches, "R32"):
        if team not in _stage_teams(matches, "R32"):
            return "final", "GROUP"

    return "pending", None


def resolve_outcomes(data, fasit):
    """Bygger fasit: dict spørsmål -> {status, value}."""
    matches = data["matches"]
    out = {}

    def O(key, status, value):
        out[key] = {"status": status, "value": value}

    # Grupperekkefølge
    tables = compute_group_tables(matches)
    for letter, table in tables.items():
        played = any(r["played"] for r in table)
        status = (
            "final"
            if _group_complete(matches, letter)
            else ("provisional" if played else "pending")
        )
        O(f"group_{letter}", status, {r["team"]: r["pos"] for r in table})

    # Jevnest gruppe (minst differanse i poeng mellom 1. og 4. plass)
    if all(_group_complete(matches, g) for g in "ABCDEFGHIJKL"):
        spreads = {g: tables[g][0]["pts"] - tables[g][3]["pts"] for g in tables}
        best = min(spreads.values())
        O(
            "jevnest",
            "final",
            sorted(f"Gruppe {g}" for g, s in spreads.items() if s == best),
        )
    else:
        O("jevnest", "pending", None)

    # Hvor langt går Norge?
    st, stage = _team_elimination(matches, "Norway")
    if st == "final":
        O(
            "norge_ut",
            "final",
            "Vinner finalen"
            if stage == "WINNER"
            else "Finale"
            if stage == "FINAL"
            else NORGE_UT_BY_STAGE[stage],
        )
    else:
        O("norge_ut", "pending", None)

    # Scorer Haiti mål?
    haiti_goals = 0
    for m in matches:
        if m["status"] != "FINISHED":
            continue
        if m["home"] == "Haiti":
            haiti_goals += m["goals_home"] or 0
        elif m["away"] == "Haiti":
            haiti_goals += m["goals_away"] or 0
    if haiti_goals > 0:
        O("haiti", "final", "Ja")
    elif _team_elimination(matches, "Haiti")[0] == "final":
        O("haiti", "final", "Nei")
    else:
        O("haiti", "pending", None)

    # Toppscorer (foreløpig til finalen er spilt)
    scorers = data.get("scorers") or []
    final_done = any(
        m["stage"] == "FINAL" and m["status"] == "FINISHED" for m in matches
    )
    if scorers and scorers[0]["goals"] > 0:
        top_goals = scorers[0]["goals"]
        top_names = [s["player"] for s in scorers if s["goals"] == top_goals]
        O("toppscorer", "final" if final_done else "provisional", top_names)
    else:
        O("toppscorer", "pending", None)

    # Vinner og taper av finalen
    final = next(
        (m for m in matches if m["stage"] == "FINAL" and m["status"] == "FINISHED"),
        None,
    )
    if final:
        winner = final["home"] if final["winner"] == "HOME_TEAM" else final["away"]
        loser = final["away"] if final["winner"] == "HOME_TEAM" else final["home"]
        O("vinner", "final", winner)
        O("taper_finale", "final", loser)
    else:
        O("vinner", "pending", None)
        O("taper_finale", "pending", None)

    # Semifinalister
    sf_teams = _stage_teams(matches, "SF")
    if _stage_known(matches, "SF"):
        O("semifinalister", "final", sorted(sf_teams))
    elif sf_teams:
        O("semifinalister", "provisional", sorted(sf_teams))
    else:
        O("semifinalister", "pending", None)

    # De fire navngitte kampene (eksakt resultat)
    for home, away in [
        ("Mexico", "South Africa"),
        ("Morocco", "Brazil"),
        ("Switzerland", "Qatar"),
        ("Norway", "Iraq"),
    ]:
        key = f"kamp_{home}_{away}"
        m = next(
            (
                m
                for m in matches
                if {m["home"], m["away"]} == {home, away}
                and m["stage"] == "GROUP"
                and m["status"] == "FINISHED"
            ),
            None,
        )
        if m:
            O(key, "final", {m["home"]: m["goals_home"], m["away"]: m["goals_away"]})
        else:
            O(key, "pending", None)

    # Kommer Sverige til 8-delsfinale (R16)?
    if "Sweden" in _stage_teams(matches, "R16"):
        O("sverige_r16", "final", "Ja")
    elif _stage_known(matches, "R16"):
        O("sverige_r16", "final", "Nei")
    else:
        st, stage = _team_elimination(matches, "Sweden")
        if st == "final" and stage in ("GROUP", "R32"):
            O("sverige_r16", "final", "Nei")
        else:
            O("sverige_r16", "pending", None)

    # Kommer et afrikansk lag til kvartfinale?
    qf_teams = _stage_teams(matches, "QF")
    if any(is_african(t) for t in qf_teams):
        O("afrika_qf", "final", "Ja")
    elif _stage_known(matches, "QF"):
        O("afrika_qf", "final", "Nei")
    else:
        O("afrika_qf", "pending", None)

    # Mål totalt i kvartfinalene (uten straffekonk)
    qf_matches = [m for m in matches if m["stage"] == "QF"]
    if qf_matches and len([m for m in qf_matches if m["status"] == "FINISHED"]) >= 4:
        total = sum(
            (m["goals_home"] or 0) + (m["goals_away"] or 0)
            for m in qf_matches
            if m["status"] == "FINISHED"
        )
        bucket = next(
            (
                b
                for b in QF_BUCKETS
                if int(b.split("-")[0]) <= total <= int(b.split("-")[1])
            ),
            QF_BUCKETS[-1],
        )
        O("qf_maal", "final", bucket)
    else:
        O("qf_maal", "pending", None)

    # Kun manuell fasit (fasit.json): hattrick, ryerson, selvmål
    O("hattrick", "pending", None)
    O("ryerson", "pending", None)
    O("selvmaal_semi", "pending", None)

    # Manuelle overstyringer vinner alltid
    for key, value in fasit.items():
        if key in ("vinner", "taper_finale"):
            value = canonical(value) or value
        if key == "semifinalister" and isinstance(value, list):
            value = sorted(canonical(t) or t for t in value)
        out[key] = {"status": "final", "value": value}

    return out


def _scorer_option_correct(predicted, actual_names):
    """Sammenligner et alternativ fra skjemaet (etternavn / 'Noen andre') med faktiske navn."""
    actual_norm = [norm(n) for n in actual_names]
    matched_options = {
        opt for opt in SCORER_OPTIONS if any(norm(opt) in n for n in actual_norm)
    }
    if norm(predicted) == norm("Noen andre"):
        return not matched_options
    return any(norm(predicted) in n for n in actual_norm)


def score_person(p, outcomes):
    """Returnerer (breakdown-liste, total, sikre_poeng)."""
    items = []

    def add(label, points, maxp, status, predicted, actual):
        items.append(
            {
                "label": label,
                "points": points,
                "max": maxp,
                "status": status,
                "predicted": predicted,
                "actual": actual,
            }
        )

    def simple(key, label, predicted, maxp, normalize=lambda x: norm(str(x))):
        o = outcomes.get(key, {"status": "pending", "value": None})
        pts = 0
        if o["status"] != "pending" and predicted is not None:
            actual = o["value"]
            ok = (
                normalize(predicted) in [normalize(a) for a in actual]
                if isinstance(actual, list)
                else normalize(predicted) == normalize(actual)
            )
            pts = maxp if ok else 0
        add(label, pts, maxp, o["status"], predicted, o["value"])

    # Grupper
    for letter in "ABCDEFGHIJKL":
        o = outcomes.get(f"group_{letter}", {"status": "pending", "value": None})
        pred = p["group_order"].get(letter, {})
        pts = 0
        if o["status"] != "pending" and o["value"]:
            pts = sum(1 for team, pos in pred.items() if o["value"].get(team) == pos)
        add(f"Gruppe {letter}", pts, 4, o["status"], pred, o["value"])

    # Jevnest gruppe (fasit kan ha flere ved poenglikhet)
    o = outcomes.get("jevnest", {"status": "pending", "value": None})
    jpts = 0
    if o["status"] != "pending" and p["jevnest"]:
        actual = o["value"] if isinstance(o["value"], list) else [o["value"]]
        jpts = 4 if norm(p["jevnest"]) in [norm(a) for a in actual] else 0
    add("Jevnest gruppe", jpts, 4, o["status"], p["jevnest"], o["value"])

    simple("norge_ut", "Norge ryker ut i", p["norge_ut"], 5)
    simple("haiti", "Scorer Haiti mål?", p["haiti"], 3)

    # Toppscorer og hattrick: alternativ-logikk («Noen andre»)
    for key, label, maxp, pred in [
        ("toppscorer", "Toppscorer", 5, p["toppscorer"]),
        ("hattrick", "Første hattrick", 5, p["hattrick"]),
    ]:
        o = outcomes.get(key, {"status": "pending", "value": None})
        pts = 0
        if o["status"] != "pending" and pred:
            actual = o["value"] if isinstance(o["value"], list) else [o["value"]]
            pts = maxp if _scorer_option_correct(pred, actual) else 0
        add(label, pts, maxp, o["status"], pred, o["value"])

    simple("vinner", "VM-vinner", p["vinner"], 20)
    simple("taper_finale", "Taper finalen", p["taper_finale"], 15)

    # Semifinalister: 4p per riktig
    o = outcomes.get("semifinalister", {"status": "pending", "value": None})
    spts = 0
    if o["status"] != "pending" and o["value"]:
        actual = {norm(t) for t in o["value"]}
        spts = 4 * sum(1 for t in p["semifinalister"] if norm(t) in actual)
    add("Semifinalister", spts, 16, o["status"], p["semifinalister"], o["value"])

    # Kampresultater
    for home, away in [
        ("Mexico", "South Africa"),
        ("Morocco", "Brazil"),
        ("Switzerland", "Qatar"),
        ("Norway", "Iraq"),
    ]:
        o = outcomes.get(f"kamp_{home}_{away}", {"status": "pending", "value": None})
        pred = p["matches"].get(frozenset((home, away)))
        pts = 0
        if o["status"] != "pending" and pred and o["value"]:
            pts = (
                4 if all(pred.get(t) == o["value"].get(t) for t in (home, away)) else 0
            )
        add(
            f"Resultat {no_name(home)}–{no_name(away)}",
            pts,
            4,
            o["status"],
            pred,
            o["value"],
        )

    simple("sverige_r16", "Sverige til 8-delsfinale?", p["sverige_r16"], 4)
    simple("afrika_qf", "Afrikansk lag i kvartfinale?", p["afrika_qf"], 4)
    simple("qf_maal", "Mål i kvartfinalene", p["qf_maal"], 4)
    simple("ryerson", "Gule kort Ryerson", p["ryerson"], 4)
    simple("selvmaal_semi", "Selvmål i semifinale?", p["selvmaal_semi"], 4)

    total = sum(i["points"] for i in items)
    secure = sum(i["points"] for i in items if i["status"] == "final")
    return items, total, secure


def compute_leaderboard(people, outcomes):
    board = []
    for p in people:
        items, total, secure = score_person(p, outcomes)
        board.append(
            {
                "name": p["name"],
                "total": total,
                "secure": secure,
                "max": sum(i["max"] for i in items),
                "vinner": no_name(p["vinner"]),
                "breakdown": items,
            }
        )
    board.sort(key=lambda b: (-b["total"], -b["secure"], b["name"]))
    rank = 0
    prev = None
    for i, b in enumerate(board):
        if (b["total"], b["secure"]) != prev:
            rank = i + 1
            prev = (b["total"], b["secure"])
        b["rank"] = rank
    return board

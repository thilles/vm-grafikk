"""D&I Tippekonkurranse VM 2026 – scoreboard-app.

Bakgrunnsjobben henter kampdata med jevne mellomrom (REFRESH_MINUTES),
beregner poeng og fakta, og frontend leser alt fra /api/state.
"""

import asyncio
import datetime
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import duell as duell_mod
from . import kg, kg_nlq
from .consensus import build_consensus
from .facts import build_facts
from .football_api import get_provider
from .highlights import build_highlights, match_key
from .highlights import view as highlights_view
from .news import build_news
from .nrk_links import build_links
from .nrk_links import url_for as nrk_url
from .predictions import load_predictions
from .scoring import (
    compute_group_tables,
    compute_leaderboard,
    compute_thirds_ranking,
    load_fasit,
    resolve_outcomes,
)
from .teams import TEAMS, confederation_of, display, flag, no_name

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
log = logging.getLogger("vm.main")

REFRESH_MINUTES = int(os.environ.get("REFRESH_MINUTES", "10"))

STATE = {"ready": False, "error": None}

# ── R32-bracket-struktur for VM 2026 ─────────────────────────────────────────
# 16 kamper: 8 direkte gruppe-parvise kamper + 8 best-treerplass-kamper.
# Hvert element: (utc_dato_prefiks, hjemme_slot, borte_slot)
# Slot-format: ("1st"/"2nd", "Gruppe") eller ("3rd", ["Gruppe", ...])
# Referanse: FIFA 2026 kamp-program, publisert av FIFA.

_R32_SLOTS = [
    ("2026-06-28", ("2nd", "A"), ("2nd", "B")),
    ("2026-06-29", ("1st", "E"), ("3rd", ["A", "B", "C", "D", "F"])),
    ("2026-06-29", ("1st", "F"), ("2nd", "C")),
    ("2026-06-29", ("1st", "C"), ("2nd", "F")),
    ("2026-06-30", ("1st", "I"), ("3rd", ["C", "D", "F", "G", "H"])),
    ("2026-06-30", ("2nd", "E"), ("2nd", "I")),
    ("2026-06-30", ("1st", "A"), ("3rd", ["C", "E", "F", "H", "I"])),
    ("2026-07-01", ("1st", "L"), ("3rd", ["E", "H", "I", "J", "K"])),
    ("2026-07-01", ("1st", "D"), ("3rd", ["B", "E", "F", "I", "J"])),
    ("2026-07-01", ("1st", "G"), ("3rd", ["A", "E", "H", "I", "J"])),
    ("2026-07-02", ("2nd", "K"), ("2nd", "L")),
    ("2026-07-02", ("1st", "H"), ("2nd", "J")),
    ("2026-07-02", ("1st", "B"), ("3rd", ["E", "F", "G", "I", "J"])),
    ("2026-07-03", ("1st", "J"), ("2nd", "H")),
    ("2026-07-03", ("1st", "K"), ("3rd", ["D", "E", "I", "J", "L"])),
    ("2026-07-03", ("2nd", "D"), ("2nd", "G")),
]


def _resolve_r32_teams(matches, tables, thirds):
    """Oppdater R32-kamper med ekte lag fra gruppetabeller der API-et returnerer TBD.

    Sorterer R32-kampene etter dato og matcher dem mot _R32_SLOTS for å hente
    riktig gruppe-posisjon for hvert lag. Bare lag som faktisk er klare (komplett
    gruppe) erstattes; ellers beholdes TBD.
    """
    r32 = sorted(
        [m for m in matches if m["stage"] == "R32"],
        key=lambda m: m["utc_date"] or "",
    )
    if not r32:
        return matches

    # Gruppertabeller: winner = indeks 0, runner-up = indeks 1
    def _group_team(pos_idx, group):
        t = tables.get(group, [])
        return t[pos_idx]["team"] if len(t) > pos_idx else None

    # Best-treer-kandidater rangert etter poeng/målforskjell (bare de 8 beste går videre)
    qualifying_thirds = [r for r in thirds if r.get("advances")]

    used_thirds = set()

    def _get_3rd(pool_groups):
        """Hent best-rangert treerplass-lag fra poolen som ikke er brukt ennå."""
        for r in qualifying_thirds:
            if r["group"] in pool_groups and r["team"] not in used_thirds:
                used_thirds.add(r["team"])
                return r["team"]
        return None

    def _resolve_slot(slot):
        pos, group_or_pool = slot
        if pos == "3rd":
            return _get_3rd(group_or_pool)
        idx = 0 if pos == "1st" else 1
        return _group_team(idx, group_or_pool)

    # Grupper slots etter dato-prefiks for å matche rekkefølge innen dagen
    slots_by_date = {}
    for date_pfx, h_slot, a_slot in _R32_SLOTS:
        slots_by_date.setdefault(date_pfx, []).append((h_slot, a_slot))

    r32_by_date = {}
    for m in r32:
        pfx = (m["utc_date"] or "")[:10]
        r32_by_date.setdefault(pfx, []).append(m)

    # Oppdater TBD-lag i API-kampene
    updated = {id(m): m for m in matches}
    for date_pfx, slots in slots_by_date.items():
        api_day = r32_by_date.get(date_pfx, [])
        for i, (h_slot, a_slot) in enumerate(slots):
            if i >= len(api_day):
                break
            m = api_day[i]
            if m["home"] not in TEAMS:
                resolved = _resolve_slot(h_slot)
                if resolved:
                    m = {**m, "home": resolved}
            if m["away"] not in TEAMS:
                resolved = _resolve_slot(a_slot)
                if resolved:
                    m = {**m, "away": resolved}
            updated[id(api_day[i])] = m

    return list(updated.values())


def _match_view(m, highlights=None, nrk=None, duell_index=None):
    return {
        "id": match_key(m),
        "date": m["utc_date"],
        "status": m["status"],
        "stage": m["stage"],
        "group": m["group"],
        "home": no_name(m["home"]),
        "away": no_name(m["away"]),
        "home_flag": flag(m["home"]),
        "away_flag": flag(m["away"]),
        "goals_home": m["goals_home"],
        "goals_away": m["goals_away"],
        "pens": f"{m['pens_home']}–{m['pens_away']} på straffer"
        if m.get("pens_home") is not None
        else None,
        "highlights": highlights_view(
            (highlights or {}).get(match_key(m)), m["home"], m["away"]
        ),
        "report_url": nrk_url(m, nrk),
        "duell": duell_mod.for_match(m, duell_index) if duell_index else None,
    }


def _bracket_match_view(m, squad_mv=None):
    """Minimavisning for sluttspillkamp – brukes av bracket-tre og sunburst."""
    mv = squad_mv or {}
    return {
        "id": match_key(m),
        "date": m["utc_date"],
        "status": m["status"],
        "stage": m["stage"],
        "home": no_name(m["home"]),
        "away": no_name(m["away"]),
        "home_flag": flag(m["home"]),
        "away_flag": flag(m["away"]),
        "home_conf": confederation_of(m["home"]),
        "away_conf": confederation_of(m["away"]),
        "home_mv": mv.get(m["home"]),
        "away_mv": mv.get(m["away"]),
        "goals_home": m["goals_home"],
        "goals_away": m["goals_away"],
        "winner": m.get("winner"),
    }


def rebuild_state():
    provider = get_provider()
    data = provider.fetch()
    matches = sorted(data["matches"], key=lambda m: m["utc_date"] or "")
    people, pred_source = load_predictions()
    fasit = load_fasit()
    outcomes = resolve_outcomes(data, fasit)
    leaderboard = compute_leaderboard(people, outcomes)
    tables = compute_group_tables(matches)
    thirds = compute_thirds_ranking(tables)

    # Fyll inn TBD-lag i R32 fra gruppetabeller der API-et ikke har lagene ennå.
    matches = _resolve_r32_teams(matches, tables, thirds)

    # Transfermarkt-lagsverdier for sunburst-vekting av uspilte kamper.
    squad_mv = kg.squad_market_values()

    finished = [m for m in matches if m["status"] == "FINISHED"]
    live = [m for m in matches if m["status"] in ("IN_PLAY", "PAUSED")]
    upcoming = [m for m in matches if m["status"] in ("SCHEDULED", "TIMED")][:8]

    # Lenke til NRKs kampside pr kamp + NIFS kamp-id-er (åpent API, ingen nøkkel).
    nrk_links = build_links(finished)
    # Mål/kort pr ferdig kamp (NRKs NIFS-API). Demo-data har dem ferdig påsatt.
    highlights = data.get("highlights") or build_highlights(matches, nrk_links)
    # Nyhetsfeed fra NRKs direkterapportering (åpent API, ingen nøkkel).
    news = build_news()
    # «Kamp i kampen»: felles klubblag pr kamp (KG). Indeksen bygges én gang her;
    # kg.club_rosters() er memoisert, så dette koster ingen SPARQL etter oppstart.
    duell_index = duell_mod.build_index()

    STATE.update(
        {
            "ready": True,
            "error": None,
            "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source": data["source"],
            "demo": data["demo"],
            "predictions_source": pred_source,
            "leaderboard": leaderboard,
            "matches": {
                "live": [_match_view(m, duell_index=duell_index) for m in live],
                "finished": [
                    _match_view(m, highlights, nrk_links, duell_index)
                    for m in finished[-12:]
                ][::-1],
                "upcoming": [_match_view(m, duell_index=duell_index) for m in upcoming],
            },
            "groups": {
                letter: [
                    {**row, "team": no_name(row["team"]), "flag": flag(row["team"])}
                    for row in table
                ]
                for letter, table in tables.items()
            },
            "scorers": [
                {**s, "team": no_name(s["team"]), "flag": flag(s["team"])}
                for s in (data.get("scorers") or [])[:5]
            ],
            "facts": build_facts(matches, people, data["demo"]),
            "consensus": build_consensus(people),
            "news": news,
            "thirds": [
                {
                    **{k: v for k, v in r.items() if k != "team"},
                    "team": no_name(r["team"]),
                    "flag": flag(r["team"]),
                    "conf": confederation_of(r["team"]),
                }
                for r in thirds
            ],
            "bracket": {
                stage: [
                    _bracket_match_view(m, squad_mv)
                    for m in sorted(
                        [mx for mx in matches if mx["stage"] == stage],
                        key=lambda mx: mx["utc_date"] or "",
                    )
                ]
                for stage in ["R32", "R16", "QF", "SF", "THIRD", "FINAL"]
            },
        }
    )
    log.info("State oppdatert: %d kamper, %d deltakere", len(matches), len(people))


async def refresher():
    while True:
        try:
            await asyncio.to_thread(rebuild_state)
        except Exception as e:
            log.exception("Oppdatering feilet")
            STATE["error"] = str(e)
        await asyncio.sleep(REFRESH_MINUTES * 60)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(refresher())
    # Forhåndslast kunnskapsgrafen enkelt-trådet, så SPARQL-parseren er varm før
    # samtidige forespørsler treffer den (pyparsing er ikke trådsikker ved
    # første parsing). Blokkerer ikke oppstart om noe feiler.
    if kg.available():
        try:
            await asyncio.get_event_loop().run_in_executor(None, kg._load)
        except Exception as e:  # noqa: BLE001
            log.warning("Forhåndslasting av kunnskapsgraf feilet: %s", e)
    yield
    task.cancel()


app = FastAPI(title="D&I Tippekonkurranse VM 2026", lifespan=lifespan)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.get("/api/state")
def api_state():
    return JSONResponse(STATE)


@app.post("/api/refresh")
def api_refresh():
    try:
        rebuild_state()
        return {"ok": True, "updated": STATE.get("updated")}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ── Kunnskapsgraf: «Utforsk grafen» ──────────────────────────────────────────

KG_QUERY_TIMEOUT = float(os.environ.get("KG_QUERY_TIMEOUT", "12"))


@app.get("/graf")
def graf():
    return FileResponse(os.path.join(STATIC_DIR, "kg.html"))


@app.get("/api/kg/info")
def api_kg_info():
    if not kg.available():
        return JSONResponse(
            {"ok": False, "error": "Kunnskapsgrafen er ikke tilgjengelig."},
            status_code=503,
        )
    try:
        return JSONResponse({"ok": True, "ask": kg_nlq.available(), **kg.info()})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def _run_kg_query(request: Request):
    if not kg.available():
        return JSONResponse(
            {"error": "Kunnskapsgrafen er ikke tilgjengelig."}, status_code=503
        )
    if request.method == "POST":
        raw = (await request.body()).decode("utf-8")
        if request.headers.get("content-type", "").startswith(
            "application/x-www-form-urlencoded"
        ):
            from urllib.parse import parse_qs

            query = (parse_qs(raw).get("query") or [raw])[0]
        else:  # application/sparql-query eller annet: rå body er spørringen
            query = raw
    else:
        query = request.query_params.get("query", "")
    limit = request.query_params.get("limit", kg.DEFAULT_LIMIT)
    try:
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, kg.run_query, query, limit),
            timeout=KG_QUERY_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return JSONResponse(
            {"error": f"Spørringen tok for lang tid (over {KG_QUERY_TIMEOUT:.0f} s)."},
            status_code=504,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=500)
    headers = {"X-Truncated": "1"} if result.get("truncated") else {}
    return Response(
        content=result["body"], media_type=result["content_type"], headers=headers
    )


@app.get("/api/kg/teams")
def api_kg_teams():
    if not kg.available():
        return JSONResponse(
            {"error": "Kunnskapsgrafen er ikke tilgjengelig."}, status_code=503
        )
    return JSONResponse({"teams": kg.team_labels()})


@app.get("/api/kg/graph")
def api_kg_graph(team: str = "Norway", view: str = "team"):
    if not kg.available():
        return JSONResponse(
            {"error": "Kunnskapsgrafen er ikke tilgjengelig."}, status_code=503
        )
    try:
        return JSONResponse(kg.full_graph() if view == "all" else kg.subgraph(team))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/kg/sparql")
async def api_kg_sparql_get(request: Request):
    return await _run_kg_query(request)


@app.post("/api/kg/sparql")
async def api_kg_sparql_post(request: Request):
    return await _run_kg_query(request)


@app.post("/api/kg/ask")
async def api_kg_ask(request: Request):
    """Naturlig språk → SPARQL via Claude (kg_nlq), kjør, og oppsummer på norsk."""
    if not kg.available():
        return JSONResponse(
            {"error": "Kunnskapsgrafen er ikke tilgjengelig."}, status_code=503
        )
    if not kg_nlq.available():
        return JSONResponse(
            {"error": "Spør-funksjonen er ikke aktivert (mangler ANTHROPIC_API_KEY)."},
            status_code=503,
        )
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    spørsmål = (body.get("spørsmål") or body.get("sporsmal") or "").strip()
    if not spørsmål:
        return JSONResponse({"error": "Tomt spørsmål."}, status_code=400)

    loop = asyncio.get_event_loop()
    import time

    t0 = time.perf_counter()
    try:
        # 1) NL → SPARQL
        sparql = await asyncio.wait_for(
            loop.run_in_executor(None, kg_nlq.to_sparql, spørsmål),
            timeout=KG_QUERY_TIMEOUT,
        )
        # 2) Kjør spørringen (read-only, med tak og lås – samme vei som /sparql)
        result = await asyncio.wait_for(
            loop.run_in_executor(None, kg.run_query, sparql, kg.DEFAULT_LIMIT),
            timeout=KG_QUERY_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return JSONResponse(
            {"error": f"Spørringen tok for lang tid (over {KG_QUERY_TIMEOUT:.0f} s)."},
            status_code=504,
        )
    except ValueError as e:
        # Ugyldig/forbudt SPARQL fra modellen – ta med spørringen så den vises i UI.
        return JSONResponse(
            {"error": str(e), "sparql": locals().get("sparql")}, status_code=400
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)

    ms = round((time.perf_counter() - t0) * 1000)
    # 3) Kort norsk svar (feiler stille → tom streng)
    svar = await loop.run_in_executor(
        None, kg_nlq.summarize, spørsmål, sparql, result["content_type"], result["body"]
    )

    payload = {
        "sparql": sparql,
        "svar": svar,
        "truncated": result.get("truncated", False),
        "ms": ms,
    }
    if "sparql-results+json" in result["content_type"]:
        import json as _json

        payload["results"] = _json.loads(result["body"])
    else:
        payload["turtle"] = result["body"]
    return JSONResponse(payload)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

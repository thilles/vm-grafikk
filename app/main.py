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
    load_fasit,
    resolve_outcomes,
)
from .teams import display, flag, no_name

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
log = logging.getLogger("vm.main")

REFRESH_MINUTES = int(os.environ.get("REFRESH_MINUTES", "10"))

STATE = {"ready": False, "error": None}


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


def rebuild_state():
    provider = get_provider()
    data = provider.fetch()
    matches = sorted(data["matches"], key=lambda m: m["utc_date"] or "")
    people, pred_source = load_predictions()
    fasit = load_fasit()
    outcomes = resolve_outcomes(data, fasit)
    leaderboard = compute_leaderboard(people, outcomes)
    tables = compute_group_tables(matches)

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

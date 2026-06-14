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

from . import kg

from .consensus import build_consensus
from .facts import build_facts
from .football_api import get_provider
from .highlights import build_highlights, match_key
from .highlights import view as highlights_view
from .news import build_news
from .nrk_links import build_links, url_for as nrk_url
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


def _match_view(m, highlights=None, nrk=None):
    return {
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
        "highlights": highlights_view((highlights or {}).get(match_key(m))),
        "report_url": nrk_url(m, nrk),
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

    # Mål/kort pr ferdig kamp (api-sports). Demo-data har dem ferdig påsatt.
    highlights = data.get("highlights") or build_highlights(matches)
    # Lenke til NRKs kampside pr kamp (NIFS åpne API, ingen nøkkel).
    nrk_links = build_links(finished)
    # Nyhetsfeed fra NRKs direkterapportering (åpent API, ingen nøkkel).
    news = build_news()

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
                "live": [_match_view(m) for m in live],
                "finished": [_match_view(m, highlights, nrk_links) for m in finished[-12:]][::-1],
                "upcoming": [_match_view(m) for m in upcoming],
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
        return JSONResponse({"ok": False, "error": "Kunnskapsgrafen er ikke tilgjengelig."},
                            status_code=503)
    try:
        return JSONResponse({"ok": True, **kg.info()})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def _run_kg_query(request: Request):
    if not kg.available():
        return JSONResponse({"error": "Kunnskapsgrafen er ikke tilgjengelig."},
                            status_code=503)
    if request.method == "POST":
        raw = (await request.body()).decode("utf-8")
        if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
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
            status_code=504)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=500)
    headers = {"X-Truncated": "1"} if result.get("truncated") else {}
    return Response(content=result["body"], media_type=result["content_type"],
                    headers=headers)


@app.get("/api/kg/sparql")
async def api_kg_sparql_get(request: Request):
    return await _run_kg_query(request)


@app.post("/api/kg/sparql")
async def api_kg_sparql_post(request: Request):
    return await _run_kg_query(request)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

"""D&I Tippekonkurranse VM 2026 – scoreboard-app.

Bakgrunnsjobben henter kampdata med jevne mellomrom (REFRESH_MINUTES),
beregner poeng og fakta, og frontend leser alt fra /api/state.
"""
import asyncio
import datetime
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .facts import build_facts
from .football_api import get_provider
from .predictions import load_predictions
from .scoring import compute_group_tables, compute_leaderboard, load_facit, resolve_outcomes
from .teams import display, flag, no_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("vm.main")

REFRESH_MINUTES = int(os.environ.get("REFRESH_MINUTES", "10"))

STATE = {"ready": False, "error": None}


def _match_view(m):
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
        "pens": f"{m['pens_home']}–{m['pens_away']} på straffer" if m.get("pens_home") is not None else None,
    }


def rebuild_state():
    provider = get_provider()
    data = provider.fetch()
    matches = sorted(data["matches"], key=lambda m: m["utc_date"] or "")
    people, pred_source = load_predictions()
    facit = load_facit()
    outcomes = resolve_outcomes(data, facit)
    leaderboard = compute_leaderboard(people, outcomes)
    tables = compute_group_tables(matches)

    finished = [m for m in matches if m["status"] == "FINISHED"]
    live = [m for m in matches if m["status"] in ("IN_PLAY", "PAUSED")]
    upcoming = [m for m in matches if m["status"] in ("SCHEDULED", "TIMED")][:8]

    STATE.update({
        "ready": True,
        "error": None,
        "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": data["source"],
        "demo": data["demo"],
        "predictions_source": pred_source,
        "leaderboard": leaderboard,
        "matches": {
            "live": [_match_view(m) for m in live],
            "finished": [_match_view(m) for m in finished[-12:]][::-1],
            "upcoming": [_match_view(m) for m in upcoming],
        },
        "groups": {
            letter: [{**row, "team": no_name(row["team"]), "flag": flag(row["team"])} for row in table]
            for letter, table in tables.items()
        },
        "scorers": [
            {**s, "team": no_name(s["team"]), "flag": flag(s["team"])}
            for s in (data.get("scorers") or [])[:5]
        ],
        "facts": build_facts(matches, people, data["demo"]),
    })
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


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

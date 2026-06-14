# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Scoreboard webapp for an internal World Cup 2026 betting competition ("D&I
Tippekonkurranse"). A FastAPI backend fetches match data, derives the correct
answers ("fasit") from that data as the tournament progresses, scores every
participant's predictions, and serves a single-page scoreboard. The codebase,
UI, and most identifiers are in Norwegian — match that when writing new code,
comments, and log messages.

## Running and developing

```bash
# Full stack via compose (reads .env beside docker-compose.yml)
docker compose up --build -d        # serves on http://localhost:8000

# Run uvicorn directly without docker (needs deps + data paths)
pip install -r requirements.txt
PREDICTIONS_XLSX=data/svar.xlsx FASIT_JSON=data/fasit.json \
  uvicorn app.main:app --reload --port 8000
```

There is no test suite, linter, or build step. Verify changes by hitting the
running app: `GET /api/state` (full computed state as JSON), `POST /api/refresh`
(force an immediate rebuild and inspect the result/error), `GET /` (scoreboard).

With no `FOOTBALL_DATA_TOKEN` set, the app runs on built-in demo data
(`DemoProvider` in `football_api.py`) and is clearly marked as demo
(`state.demo == true`) — convenient for local work without an API key.

### Key environment variables

- `FOOTBALL_DATA_TOKEN` — football-data.org v4 key. Absent → demo data.
- `APISPORTS_KEY` — api-sports key for per-match goals/cards (highlights).
  Absent → highlights disabled, rest of the app unchanged.
- `HIGHLIGHTS_CACHE` — path for the highlights cache, default
  `/data/highlights_cache.json`. `APISPORTS_MAX_CALLS_PER_REFRESH` (default 15)
  caps api-sports calls per refresh.
- NRK match-page links (`nrk_links.py`) and the news feed (`news.py`) use NRK's
  open NIFS/serum APIs and need no key. `NIFS_TOURNAMENT_ID` (default 56 = the
  World Cup) and `NIFS_SEASON_YEAR` (default 2026) pick the tournament/season;
  `NRK_LINKS_CACHE` is the link-cache path. Matches are joined to NIFS by parsing
  the (Norwegian) team names through `teams.canonical`, same as the other sources.
- `SHEET_CSV_URL` — published Google Sheet CSV of predictions. Takes priority
  over the local Excel file; required in the cloud (no local file there).
- `PREDICTIONS_XLSX` — local predictions file, default `/data/svar.xlsx`.
- `FASIT_JSON` — manual-answers file, default `/data/fasit.json`.
- `REFRESH_MINUTES` — background refresh interval (default 10).
- `COMPETITION_CODE` — football-data competition, default `WC`.
- `PORT` — cloud platforms set this; Dockerfile honors it (local default 8000).
- `KG_TTL` — path to the squads knowledge-graph Turtle file, default
  `wc2026-kg/wc2026.ttl` (baked into the image). `KG_QUERY_TIMEOUT` (default 12s)
  caps each `/api/kg/sparql` query. See "Knowledge graph" below.

## Architecture

The whole app is a periodically-recomputed in-memory `STATE` dict that the
frontend polls. There is no database; everything is recomputed from scratch on
each refresh.

**Data flow per refresh** (`app/main.py:rebuild_state`, run on startup and every
`REFRESH_MINUTES` by the `refresher()` background task):

1. `football_api.get_provider().fetch()` → normalized matches + scorers
   (real API or demo).
2. `predictions.load_predictions()` → list of participants, each a dict of their
   answers (parsed from CSV/XLSX).
3. `scoring.load_fasit()` → manual overrides from `fasit.json`.
4. `scoring.resolve_outcomes(data, fasit)` → the derived **fasit**: a dict of
   `question_key → {status, value}`.
5. `scoring.compute_leaderboard(people, outcomes)` → per-person scored breakdown,
   sorted and ranked.
6. `compute_group_tables`, `facts.build_facts`, `consensus.build_consensus` fill
   in the rest of `STATE`.

**`app/teams.py` is the canonicalization hub.** All team names — from the API,
from the Excel/CSV headers and cells, and from `fasit.json` — are funneled
through `canonical()` (alias/accent-insensitive lookup via `norm()`) so the rest
of the code compares stable canonical English keys. `TEAMS` maps each canonical
name to its Norwegian display name, flag emoji, group letter, confederation, and
aliases. Display helpers (`no_name`, `flag`, `display`) convert back to Norwegian
only at the view layer. When teams change (e.g. real draw replaces placeholders),
edit `TEAMS` and its aliases here.

**Scoring (`app/scoring.py`) is the core domain logic.** Each question is
resolved to a status of `pending` / `provisional` / `final`:
- `resolve_outcomes` derives answers from match data (group standings, knockout
  bracket teams, eliminations, top scorers, named fixtures, etc.). Knockout-based
  outcomes only become known once a stage's full set of teams is present
  (`_stage_known` / `STAGE_SIZE`).
- `score_person` applies the points rules. Point values and partial-credit rules
  are documented in the module docstring and the README scoring table; some are
  assumptions the README flags as easy to change (e.g. 1pt per correct group
  placement, 4pt for exact scoreline, 4pt per correct semifinalist).
- The leaderboard distinguishes `total` (incl. provisional) from `secure` (only
  `final` outcomes); provisional points show with `*` in the UI.
- Three questions can't be derived from the free API tier (`hattrick`,
  `ryerson`, `selvmaal_semi`) and stay `pending` until set in `fasit.json`.
  Any key in `fasit.json` overrides the derived answer and is treated as `final`.

**Predictions parsing (`app/predictions.py`)** maps Google Forms column headers
to answer fields via regexes/`startswith` checks against the exact Norwegian
question text. The four named match-result fixtures and the per-group placement
columns are reconstructed by pairing/ grouping related columns. If the form's
wording or the set of named fixtures changes, update the header matching here and
the corresponding `known_fixtures` lists (which also appear in `scoring.py`).

**Question keys must stay in sync across three files**: `resolve_outcomes`
(scoring.py) produces them, `score_person` (scoring.py) consumes them, and
`predictions.py` populates the matching prediction fields. The named-fixture and
group lists are duplicated between `predictions.py` and `scoring.py` — change
both together.

`football_api.py` self-throttles against football-data.org rate-limit headers
(429 backoff + proactive wait when near the per-minute limit), and computes goals
excluding penalty sh-out scores (knockout matches use regular+extra time).

**Match highlights (`app/highlights.py`)** is a separate, optional data source
for the click-to-expand goals/cards on finished matches — football-data's free
tier exposes no match events. It uses api-sports, whose free tier blocks
`?league=&season=2026` but **does** serve WC matches via `?date=YYYY-MM-DD`
(returns fixture ids) + `?id=` (returns events). Events are immutable once a
match is `FINISHED`, so they're fetched once per match and cached (in-memory +
best-effort JSON file), with a per-refresh call cap — keeping usage to a handful
of calls/day under the 100/day free limit. football-data and api-sports matches
are joined by `match_key(m)` = `"<date>|<canonical teams sorted>"` (both sides
go through `teams.py:canonical`). `build_highlights(matches)` is a no-op when
`APISPORTS_KEY` is unset; `DemoProvider` returns sample highlights so the UI is
testable offline. `main.py` attaches the view (flag + Norwegian name per
event) onto finished matches in `_match_view`.

## Frontend

`app/static/{index.html,app.js,style.css}` — a static single page that polls
`/api/state` (about once a minute) and renders leaderboard, matches, group
tables, scorers, facts, and the "Kontoret stemte" consensus polls. No build step;
edit the files directly.

## Knowledge graph: WC-2026 squads explorer

A second, **independent** subsystem (added on top of the betting app). `wc2026-kg/`
is a standalone Python pipeline that builds an RDF/Turtle knowledge graph of all
48 World Cup squads (~1248 players) from Wikipedia + Wikidata; the FastAPI app
then serves a read-only SPARQL explorer over the resulting Turtle at `/graf`.
This subsystem shares no state with the betting app's `STATE`/refresh loop — it is
loaded lazily and read-only.

- **Build pipeline** (`wc2026-kg/build.py`, has its own venv + `requirements.txt`
  + `README.md`): acquire (MediaWiki API + BeautifulSoup, club→league/country from
  Wikidata) → custom OWL ontology (`ontology.py`, the TBox) + ABox (`graph.py`) →
  emits `ontology.ttl`, `data.ttl`, and combined `wc2026.ttl`. Idempotent; all raw
  responses cached to `wc2026-kg/cache/` (gitignored). `uris.py` builds
  deterministic URIs (slug only in the local part; full diacritics kept in
  literals); `lookups.py` is the 48-nation fallback (FIFA codes, confederations).
  Run: `python -m venv wc2026-kg/.venv && wc2026-kg/.venv/bin/pip install -r
  wc2026-kg/requirements.txt && wc2026-kg/.venv/bin/python wc2026-kg/build.py`.
- **Market values** are scraped per nation from Transfermarkt
  (`wc2026-kg/scrape_transfermarkt.py`, via the `land_id` filter → `market_values.json`,
  keyed by `slug(name)-yearOfBirth`) and baked into the graph by `build.py`. Real
  but static (not live); ~1136/1248 players covered.
- **Runtime** (`app/kg.py`): lazy-loads `KG_TTL` into an in-memory rdflib `Graph`.
  Endpoints in `main.py`: `GET /graf` (page = `app/static/kg.html` + `kg-graph.js`
  + `kg.js`), `GET /api/kg/info`, `GET /api/kg/teams`, `GET /api/kg/graph?view=
  team|groups|confed`, and `GET|POST /api/kg/sparql`.
- **SPARQL is read-only**: queries run through rdflib `Graph.query()`, which only
  executes SELECT/ASK/CONSTRUCT/DESCRIBE — UPDATE/INSERT raise and return 400.
  Results are capped by row count, query length, and a timeout.
- `rdflib` and `pyparsing` are **pinned together** in the top-level
  `requirements.txt`; the Docker base image is `python:3.12-slim`.
- **Concurrency gotcha:** pyparsing's SPARQL parser is *not thread-safe on its
  first parse* (its arity detection mutates shared state). FastAPI runs the sync
  `/api/kg/*` endpoints in a threadpool and the frontend fires several at once, so
  `kg.py` serializes graph load + every `g.query()` behind a lock and pre-warms
  the parser at startup (`lifespan` → `kg._load`). Removing that lock reintroduces
  intermittent `Param.postParse2() missing ... 'tokenList'` 500s under load.
- **To change what production shows**: re-run the `wc2026-kg` build, commit the
  regenerated `wc2026-kg/wc2026.ttl` (the app reads *that file*, not the cache or
  the json), and push. The Dockerfile copies `wc2026-kg/wc2026.ttl` into the image.

## Deployment

Dockerized; deployed on Render's free tier (auto-deploys on push to the repo).
The free tier has **no persistent disk**, so `data/fasit.json` is baked into the
image (`Dockerfile` copies `data/` to `/data`) — to update manual answers in
production, commit `fasit.json` and push. Locally, `./data` is mounted over that.
`.env` and `data/svar.xlsx` are gitignored (they hold the API key and
participants' answers). The squads knowledge graph (`wc2026-kg/wc2026.ttl`) is
likewise baked into the image (see "Knowledge graph").

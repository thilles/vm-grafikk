# NRK/NIFS-høydepunkter med innebygd video og vertikal tidslinje — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bytt kamphøydepunkt-kilden fra api-sports til NRKs NIFS-API, vis mål/kort som en vertikal tidslinje, og la mål spille NRK-videoklipp i en modal på app-siden.

**Architecture:** `highlights.py` skrives om til å hente NIFS-hendelser (`api.nifs.no/matches/<id>/`) via kamp-id-ene `nrk_links.py` allerede resolver. Et nytt lite `nrk_video.py` resolver klipp-uuid → HLS via NRK psapi, eksponert som `/api/highlights/clip/{uuid}`. Frontend tegner en vertikal tidslinje og spiller klipp via hls.js (CDN) i en modal.

**Tech Stack:** Python 3.12 / FastAPI / httpx (backend), vanilla JS + hls.js (frontend). Ingen byggsteg, ingen pytest — verifisering skjer ved å kjøre appen og kjøre frittstående Python-/curl-sjekker (jf. CLAUDE.md).

**Verifisert NIFS-hendelsestaksonomi** (mot reelle VM-2026-kamper og sluttresultat):

| matchEventTypeId | betydning | i UI |
|---|---|---|
| 2 | mål (også straffemål) | ⚽ |
| 8 | selvmål | ⚽ «(selvmål)» |
| 4 | gult kort | 🟨 |
| 3 | rødt kort | 🟥 |
| 9 / 10 | straffe tildelt (samme spiller, rett før mål) | brukes til å merke mål «(str)» |

Hver hendelse har `team.name`, `person.name`, `time` (absolutt kampminutt) + `overtime` (tilleggstid), og evt. `videos: [{source:"NRK", url:"<uuid>"}]`.

---

## Filstruktur

- **Endres:** `app/highlights.py` — omskrives fra api-sports til NIFS. Ansvar: hente + normalisere hendelser per ferdig kamp, cache, og berike for frontend (tidslinje med side + video).
- **Opprettes:** `app/nrk_video.py` — én jobb: resolve klipp-uuid → `{m3u8, playable, geoBlocked}` via NRK psapi.
- **Endres:** `app/main.py` — rekkefølge på `build_links`/`build_highlights`, send hjemme/borte til `view()`, nytt endepunkt `/api/highlights/clip/{uuid}`.
- **Endres:** `app/football_api.py` — demo-høydepunktene får `video`-felt (None) så demo-UI fortsatt fungerer.
- **Endres:** `app/static/app.js` — vertikal tidslinje + video-modal-logikk.
- **Endres:** `app/static/index.html` — hls.js-script + modal-container.
- **Endres:** `app/static/style.css` — tidslinje- og modal-stiler.
- **Endres:** `CLAUDE.md`, `README.md` — api-sports → NRK/NIFS.

---

## Task 1: Skriv om `highlights.py` til NIFS-kilde

**Files:**
- Modify: `app/highlights.py` (full omskriving)

- [ ] **Step 1: Erstatt hele fila med NIFS-implementasjonen**

```python
"""Kamphøydepunkter (mål + kort) fra NRKs NIFS-API (api.nifs.no).

api-sports' gratisplan er ikke brukbar. NRKs resultatsider kjører på NTBs
NIFS-data – det samme åpne, nøkkelfrie API-et som nrk_links.py bruker. Vi
gjenbruker kamp-id-ene nrk_links.build_links allerede resolver, henter hele
kampobjektet (GET /matches/<id>/) og trekker ut hendelsene fra matchEvents.

Hendelser er uforanderlige etter at kampen er ferdig, så de hentes én gang pr
kamp og caches (in-memory + best-effort til fil). En moderat per-oppdatering-
grense begrenser kald oppstart (NIFS er nøkkelfri, men det er høflig).
"""

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


def _normalize_events(match_obj):
    """Trekker ut mål og kort fra et NIFS-kampobjekt."""
    evs = match_obj.get("matchEvents") or []

    # Spillere som fikk straffe tildelt (type 9/10) – for å merke målet «(str)».
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


def _minkey(x):
    head = (x.get("minute") or "0").split("+")[0]
    return int(head) if head.isdigit() else 0


def _nifs_id(m, links):
    """NIFS-kamp-id for kampen fra nrk_links-kartet, ellers None."""
    entries = (links or {}).get(pair_key(m))
    if not entries:
        return None
    md = (m.get("utc_date") or "")[:10]
    best = min(entries, key=lambda e: abs(_daydiff(e.get("date"), md)))
    return best.get("id")


def _daydiff(a, b):
    import datetime
    try:
        da = datetime.date.fromisoformat((a or "")[:10])
        db = datetime.date.fromisoformat((b or "")[:10])
        return abs((da - db).days)
    except ValueError:
        return 0


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
```

- [ ] **Step 2: Verifiser mot en reell NIFS-kamp (Haiti–Skottland)**

Run:
```bash
cd /Users/thomas/Utvikling/vm-grafikk
python3 -c '
import httpx, json
from app.highlights import _normalize_events, view
m = httpx.get("https://api.nifs.no/matches/2536540/", headers={"User-Agent":"vm-grafikk/1.0"}).json()
hl = _normalize_events(m)
print("goals:", json.dumps(hl["goals"], ensure_ascii=False))
print("cards:", len(hl["cards"]))
v = view(hl, "Haiti", "Scotland")
print("events sides:", [(e["kind"], e["side"], e["minute"]) for e in v["events"]])
'
```
Expected: minst ett mål (John McGinn, 27', type normal, video=uuid), flere gule kort, og `events` sortert stigende på minutt med side home/away satt.

- [ ] **Step 3: Verifiser selvmål-merking (Belgia–Egypt)**

Run:
```bash
cd /Users/thomas/Utvikling/vm-grafikk
python3 -c '
import httpx, json
from app.highlights import _normalize_events
# finn Belgia-Egypt sin NIFS-id via stages
import urllib.request
def get(p):
    r=urllib.request.Request("https://api.nifs.no"+p,headers={"User-Agent":"vm-grafikk/1.0"})
    return json.load(urllib.request.urlopen(r))
for s in [x for x in get("/tournaments/56/stages/") if x.get("yearStart")==2026]:
    for mm in get(f"/stages/{s[\"id\"]}/matches/"):
        if mm.get("name")=="Belgia - Egypt":
            hl=_normalize_events(get(f"/matches/{mm[\"id\"]}/"))
            print([(g[\"player\"], g[\"type\"]) for g in hl[\"goals\"]])
'
```
Expected: to mål, hvorav ett har `type == "own"` (selvmålet).

- [ ] **Step 4: Commit**

```bash
git add app/highlights.py
git commit -m "Høydepunkter: hent mål/kort fra NRKs NIFS-API i stedet for api-sports"
```

---

## Task 2: Wire `main.py` mot ny `build_highlights`-signatur

**Files:**
- Modify: `app/main.py:84-86` (rebuild_state), `app/main.py:47-66` (_match_view)

- [ ] **Step 1: Bygg lenker før høydepunkter og send kartet inn**

I `rebuild_state`, erstatt blokken (rundt linje 83–86):

```python
    # Mål/kort pr ferdig kamp (api-sports). Demo-data har dem ferdig påsatt.
    highlights = data.get("highlights") or build_highlights(matches)
    # Lenke til NRKs kampside pr kamp (NIFS åpne API, ingen nøkkel).
    nrk_links = build_links(finished)
```

med:

```python
    # Lenke til NRKs kampside pr kamp (NIFS åpne API, ingen nøkkel). Bygges først
    # fordi høydepunktene gjenbruker NIFS-kamp-id-ene herfra.
    nrk_links = build_links(finished)
    # Mål/kort pr ferdig kamp (NIFS). Demo-data har dem ferdig påsatt.
    highlights = data.get("highlights") or build_highlights(matches, nrk_links)
```

- [ ] **Step 2: Send hjemme/borte til highlights_view**

I `_match_view`, erstatt linje 63:

```python
        "highlights": highlights_view((highlights or {}).get(match_key(m))),
```

med:

```python
        "highlights": highlights_view(
            (highlights or {}).get(match_key(m)), m["home"], m["away"]
        ),
```

- [ ] **Step 3: Verifiser at appen bygger state uten feil (demo)**

Run:
```bash
cd /Users/thomas/Utvikling/vm-grafikk
python3 -c '
from app.main import rebuild_state, STATE
rebuild_state()
fin = STATE["matches"]["finished"]
print("ferdige kamper:", len(fin))
ex = next((m for m in fin if m["highlights"]), None)
import json; print(json.dumps(ex["highlights"], ensure_ascii=False, indent=1) if ex else "ingen høydepunkter")
'
```
Expected: minst én ferdig kamp med `highlights.events` (demo-data), hver event har `side` og `kind`. Ingen exceptions.

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "Høydepunkter: send NIFS-lenkekart + hjemme/borte til build_highlights/view"
```

---

## Task 3: Klipp-resolver `nrk_video.py` + endepunkt

**Files:**
- Create: `app/nrk_video.py`
- Modify: `app/main.py` (import + nytt endepunkt etter `/api/state`)

- [ ] **Step 1: Opprett `app/nrk_video.py`**

```python
"""Resolver et NRK-klipp-uuid til en spillbar HLS-strøm via NRKs psapi.

NIFS-hendelsene gir en klipp-uuid pr mål. NRKs psapi gir manifestet:
  GET https://psapi.nrk.no/playback/manifest/clip/<uuid>
-> playable.assets[].url (ukryptert HLS .m3u8). Manifestet sier også om klippet
er geoblokkert (Norge) og om ekstern innbygging er tillatt. Nøkkelfritt.
"""

import logging
import re

import httpx

log = logging.getLogger("vm.nrk_video")

PSAPI = "https://psapi.nrk.no/playback/manifest/clip/{uuid}"
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{20,40}$")
_HEADERS = {"Accept": "application/json", "User-Agent": "vm-grafikk/1.0"}


def resolve_clip(uuid):
    """Returnerer {m3u8, playable, geoBlocked} eller None ved feil/ugyldig uuid."""
    if not uuid or not _UUID_RE.match(uuid):
        return None
    try:
        resp = httpx.get(PSAPI.format(uuid=uuid), headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        d = resp.json()
    except httpx.HTTPError as e:
        log.warning("psapi-oppslag feilet for %s: %s", uuid, e)
        return None

    playable = d.get("playability") == "playable"
    avail = d.get("availability") or {}
    m3u8 = None
    for a in (d.get("playable") or {}).get("assets") or []:
        if a.get("format") == "HLS" and a.get("url"):
            m3u8 = a["url"]
            break
    return {
        "m3u8": m3u8,
        "playable": bool(playable and m3u8),
        "geoBlocked": bool(avail.get("isGeoBlocked")),
    }
```

- [ ] **Step 2: Importer i `main.py`**

Etter linje 26 (`from .news import build_news`), legg til:

```python
from .nrk_video import resolve_clip
```

- [ ] **Step 3: Legg til endepunkt etter `/api/state` (rundt linje 161)**

```python
@app.get("/api/highlights/clip/{uuid}")
async def api_highlight_clip(uuid: str):
    info = resolve_clip(uuid)
    if not info or not info["m3u8"]:
        return JSONResponse({"error": "Fant ikke klipp."}, status_code=404)
    return JSONResponse(info)
```

- [ ] **Step 4: Verifiser klipp-resolving mot ekte uuid**

Run:
```bash
cd /Users/thomas/Utvikling/vm-grafikk
python3 -c '
from app.nrk_video import resolve_clip
print(resolve_clip("244a1d04-07ba-4941-93d8-dbf63b9c7d22"))
print("ugyldig:", resolve_clip("ikke-en-uuid"))
'
```
Expected: dict med `m3u8` som peker på en `.m3u8`-URL, `playable: True`, `geoBlocked: True`. Ugyldig uuid → `None`.

- [ ] **Step 5: Commit**

```bash
git add app/nrk_video.py app/main.py
git commit -m "Høydepunkter: /api/highlights/clip resolver NRK-klipp til HLS via psapi"
```

---

## Task 4: Demo-data får `video`-felt

**Files:**
- Modify: `app/football_api.py:150-172` (demo highlights)

- [ ] **Step 1: Legg `video: None` på demo-målene**

I `highlights`-dict-en, legg til `"video": None` på hvert mål-objekt (begge kampene). Eksempel for første kamp:

```python
                "goals": [
                    {"team": "Mexico", "player": "S. Giménez", "minute": "12", "type": "normal", "video": None},
                    {"team": "South Africa", "player": "L. Mokoena", "minute": "34", "type": "penalty", "video": None},
                    {"team": "Mexico", "player": "H. Lozano", "minute": "78", "type": "normal", "video": None},
                ],
```

Og for den andre demo-kampen (Brasil–Marokko):

```python
                "goals": [
                    {"team": "Morocco", "player": "Y. En-Nesyri", "minute": "23", "type": "normal", "video": None},
                    {"team": "Brazil", "player": "Vinícius Jr.", "minute": "61", "type": "normal", "video": None},
                    {"team": "Brazil", "player": "Rodrygo", "minute": "88", "type": "normal", "video": None},
                ],
```

- [ ] **Step 2: Verifiser at demo-state fortsatt rendrer høydepunkter**

Run:
```bash
cd /Users/thomas/Utvikling/vm-grafikk
python3 -c '
from app.main import rebuild_state, STATE
rebuild_state()
ev = [m["highlights"] for m in STATE["matches"]["finished"] if m["highlights"]]
print("kamper m/høydepunkter:", len(ev))
print("eksempel-event:", ev[0]["events"][0] if ev else None)
'
```
Expected: minst én kamp, første event har feltene `kind`, `side`, `flag`, `player`, `minute` (og `video` på mål).

- [ ] **Step 3: Commit**

```bash
git add app/football_api.py
git commit -m "Demo: legg video-felt på demo-høydepunktene"
```

---

## Task 5: Frontend – vertikal tidslinje

**Files:**
- Modify: `app/static/app.js:69-87` (erstatt goalLabel/cardLabel/highlightsBlock)
- Modify: `app/static/style.css` (legg til tidslinje-stiler på slutten)

- [ ] **Step 1: Erstatt `goalLabel`, `cardLabel`, `highlightsBlock` med tidslinje**

Erstatt linje 69–87 i `app.js` med:

```javascript
function eventIcon(e) {
  if (e.kind === "goal") return "⚽";
  return e.card === "RED" ? "🟥" : "🟨";
}

function eventSuffix(e) {
  if (e.kind !== "goal") return "";
  return e.type === "penalty" ? " (str)" : e.type === "own" ? " (selvmål)" : "";
}

function timelineRow(e) {
  const playable = e.kind === "goal" && e.video;
  const label =
    `${eventIcon(e)} ${e.minute}' ${e.flag} ${e.player}${eventSuffix(e)}` +
    (playable ? ' <span class="hl-play">▶</span>' : "");
  const cell = playable
    ? `<button class="hl-event hl-clip" data-clip="${e.video}" data-title="${e.player} ${e.minute}'">${label}</button>`
    : `<span class="hl-event">${label}</span>`;
  return `<div class="hl-row hl-${e.side}"><div class="hl-cell">${cell}</div></div>`;
}

function highlightsBlock(h) {
  if (!h || !h.events || !h.events.length) return "";
  const rows = h.events.map(timelineRow).join("");
  return `<div class="hl-timeline">
      <div class="hl-cap">Start</div>
      ${rows}
      <div class="hl-cap">Slutt</div>
    </div>`;
}
```

- [ ] **Step 2: Legg til tidslinje-stiler i `style.css`**

Legg til på slutten av fila:

```css
/* Vertikal høydepunkt-tidslinje */
.hl-timeline {
  position: relative;
  margin: 0.5rem 0;
  padding: 0.25rem 0;
}
.hl-timeline::before {
  content: "";
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--border, #444);
  transform: translateX(-50%);
}
.hl-cap {
  text-align: center;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  opacity: 0.6;
  position: relative;
  margin: 0.25rem 0;
}
.hl-row {
  display: flex;
  position: relative;
  margin: 0.35rem 0;
}
.hl-row .hl-cell {
  width: 50%;
  box-sizing: border-box;
}
.hl-home .hl-cell {
  text-align: right;
  padding-right: 1rem;
}
.hl-away {
  justify-content: flex-end;
}
.hl-away .hl-cell {
  text-align: left;
  padding-left: 1rem;
}
.hl-event {
  display: inline-block;
  font-size: 0.9rem;
}
button.hl-clip {
  background: none;
  border: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
  padding: 0;
}
button.hl-clip:hover {
  text-decoration: underline;
}
.hl-play {
  font-size: 0.7rem;
  opacity: 0.8;
}
```

- [ ] **Step 3: Verifiser rendring i nettleseren**

Run (i bakgrunn) og åpne i nettleser:
```bash
cd /Users/thomas/Utvikling/vm-grafikk
PREDICTIONS_XLSX=data/svar.xlsx FASIT_JSON=data/fasit.json python3 -m uvicorn app.main:app --port 8000 &
sleep 3 && curl -s localhost:8000/api/state | python3 -c 'import sys,json; d=json.load(sys.stdin); print([e for m in d["matches"]["finished"] if m["highlights"] for e in m["highlights"]["events"]][:2])'
```
Expected: events-objekter i JSON. Åpne `http://localhost:8000`, utvid en ferdig kamp, og bekreft visuelt: sentral loddrett linje, «Start»/«Slutt», hjemmelag venstre / bortelag høyre, mål med ▶. (Stopp serveren etterpå.)

- [ ] **Step 4: Commit**

```bash
git add app/static/app.js app/static/style.css
git commit -m "Frontend: vis høydepunkter som vertikal tidslinje"
```

---

## Task 6: Frontend – video-modal med hls.js

**Files:**
- Modify: `app/static/index.html` (hls.js-script + modal-container)
- Modify: `app/static/app.js` (modal-logikk + klikk-håndtering)
- Modify: `app/static/style.css` (modal-stiler)

- [ ] **Step 1: Legg hls.js og modal-container i `index.html`**

Rett før `</body>`, legg til:

```html
    <div id="clip-modal" class="clip-modal" hidden>
      <div class="clip-box">
        <button class="clip-close" aria-label="Lukk">✕</button>
        <h4 class="clip-title"></h4>
        <video class="clip-video" controls playsinline></video>
        <p class="clip-msg" hidden></p>
      </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@1/dist/hls.min.js"></script>
```

(Behold den eksisterende `<script src="app.js">`-linja slik den er, etter denne.)

- [ ] **Step 2: Legg modal-logikk i `app.js`**

Legg til på slutten av fila:

```javascript
// ---- Video-modal for NRK-klipp ----
let _hls = null;

function closeClip() {
  const modal = document.getElementById("clip-modal");
  const video = modal.querySelector(".clip-video");
  video.pause();
  video.removeAttribute("src");
  video.load();
  if (_hls) {
    _hls.destroy();
    _hls = null;
  }
  modal.hidden = true;
}

async function openClip(uuid, title) {
  const modal = document.getElementById("clip-modal");
  const video = modal.querySelector(".clip-video");
  const msg = modal.querySelector(".clip-msg");
  modal.querySelector(".clip-title").textContent = title || "Høydepunkt";
  msg.hidden = true;
  video.hidden = false;
  modal.hidden = false;

  let info;
  try {
    const r = await fetch(`/api/highlights/clip/${uuid}`);
    if (!r.ok) throw new Error("not found");
    info = await r.json();
  } catch (e) {
    video.hidden = true;
    msg.hidden = false;
    msg.textContent = "Fikk ikke hentet klippet. Prøv NRK-lenken under kampen.";
    return;
  }

  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = info.m3u8; // Safari spiller HLS nativt
  } else if (window.Hls && window.Hls.isSupported()) {
    _hls = new window.Hls();
    _hls.loadSource(info.m3u8);
    _hls.attachMedia(video);
  } else {
    video.src = info.m3u8;
  }
  video.play().catch(() => {});
}

document.addEventListener("click", (ev) => {
  const clip = ev.target.closest(".hl-clip");
  if (clip) {
    ev.stopPropagation();
    openClip(clip.dataset.clip, clip.dataset.title);
    return;
  }
  const modal = document.getElementById("clip-modal");
  if (ev.target.closest(".clip-close") || ev.target.id === "clip-modal") {
    closeClip();
  }
});
```

- [ ] **Step 3: Legg modal-stiler i `style.css`**

Legg til på slutten:

```css
/* Video-modal for NRK-klipp */
.clip-modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.clip-modal[hidden] {
  display: none;
}
.clip-box {
  background: var(--card, #1c1c1c);
  border-radius: 8px;
  padding: 1rem;
  max-width: min(90vw, 720px);
  width: 100%;
  position: relative;
}
.clip-close {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  background: none;
  border: none;
  color: inherit;
  font-size: 1.2rem;
  cursor: pointer;
}
.clip-title {
  margin: 0 1.5rem 0.5rem 0;
}
.clip-video {
  width: 100%;
  border-radius: 4px;
  background: #000;
}
.clip-msg {
  opacity: 0.8;
}
```

- [ ] **Step 4: Verifiser avspilling i nettleseren (fra norsk IP)**

Run:
```bash
cd /Users/thomas/Utvikling/vm-grafikk
FOOTBALL_DATA_TOKEN= PREDICTIONS_XLSX=data/svar.xlsx FASIT_JSON=data/fasit.json python3 -m uvicorn app.main:app --port 8000 &
sleep 3 && curl -s "localhost:8000/api/highlights/clip/244a1d04-07ba-4941-93d8-dbf63b9c7d22" | python3 -m json.tool
```
Expected: JSON med `m3u8`, `playable: true`. Åpne `http://localhost:8000`, utvid en ekte ferdig kamp (krever `FOOTBALL_DATA_TOKEN` for live data) eller test mot demo + manuell klikk; klikk et mål med ▶ → modal åpnes og klippet spiller (geoblokkert → kun fra norsk IP). Lukk med ✕ eller klikk utenfor. (Stopp serveren etterpå.)

- [ ] **Step 5: Commit**

```bash
git add app/static/index.html app/static/app.js app/static/style.css
git commit -m "Frontend: spill NRK-høydepunktklipp i modal (hls.js)"
```

---

## Task 7: Oppdater dokumentasjon

**Files:**
- Modify: `CLAUDE.md` (highlights-avsnittet + env-variabler)
- Modify: `README.md` (omtale av høydepunktkilde)

- [ ] **Step 1: Oppdater `CLAUDE.md`**

I "Key environment variables": fjern `APISPORTS_KEY`-, `HIGHLIGHTS_CACHE`- (behold stien, men oppdater beskrivelsen) og `APISPORTS_MAX_CALLS_PER_REFRESH`-punktene som omtaler api-sports. Erstatt med en beskrivelse av at høydepunkter nå kommer fra NIFS (nøkkelfritt), og nevn `HIGHLIGHTS_MAX_PER_REFRESH` (default 20) og `HIGHLIGHTS_CACHE`.

Erstatt **"Match highlights (`app/highlights.py`)"**-avsnittet i Architecture med:

```
**Match highlights (`app/highlights.py`)** is the goals/cards source for the
click-to-expand timeline on finished matches. It uses NRK's open NIFS API
(`api.nifs.no`, no key) — the same source as `nrk_links.py` — reusing the NIFS
match ids that `build_links` resolves. For each finished match it fetches
`/matches/<id>/` once and extracts goals (event type 2; own goals type 8;
penalties when the scorer also has a type 9/10 award), and cards (type 4 yellow,
type 3 red), caching them (in-memory + JSON file) since events are immutable once
`FINISHED`. Each goal carries an optional NRK clip uuid; `app/nrk_video.py`
resolves it to an HLS stream via NRK psapi, served at
`GET /api/highlights/clip/{uuid}`. `highlights.view()` merges goals+cards into one
minute-sorted timeline tagged with home/away side. `DemoProvider` returns sample
highlights (no clips) so the UI is testable offline.
```

- [ ] **Step 2: Oppdater `README.md`**

Søk etter omtale av api-sports / høydepunkter i README og erstatt med at høydepunkter (mål, kort og NRK-videoklipp) hentes fra NRKs NIFS-API, vises som en vertikal tidslinje, og at klipp spilles i en modal på siden (geoblokkert til Norge).

Run for å finne treff:
```bash
cd /Users/thomas/Utvikling/vm-grafikk
grep -ni "api-sports\|apisports\|høydepunkt" README.md
```

- [ ] **Step 3: Verifiser at ingen api-sports-referanser gjenstår i koden**

Run:
```bash
cd /Users/thomas/Utvikling/vm-grafikk
grep -rni "apisports\|api-sports\|x-apisports" app/ CLAUDE.md README.md
```
Expected: ingen treff (tom output).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "Docs: høydepunkter kommer nå fra NRK/NIFS, ikke api-sports"
```

---

## Sluttverifisering

- [ ] **Kjør hele appen mot demo og bekreft manuelt**

```bash
cd /Users/thomas/Utvikling/vm-grafikk
PREDICTIONS_XLSX=data/svar.xlsx FASIT_JSON=data/fasit.json python3 -m uvicorn app.main:app --port 8000 &
sleep 3
curl -s localhost:8000/api/state | python3 -c 'import sys,json; d=json.load(sys.stdin); print("demo:", d["demo"]); print("events:", [m["highlights"]["events"][0] for m in d["matches"]["finished"] if m["highlights"]][:1])'
```
Expected: `/api/state` svarer, ferdige kamper har `highlights.events` med `side`/`kind`. Åpne `http://localhost:8000` og bekreft tidslinjen visuelt. Stopp serveren.

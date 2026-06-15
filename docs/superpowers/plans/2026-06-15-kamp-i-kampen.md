# «Kamp i kampen» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a user expands a match card, show a small force-directed node graph («Kamp i kampen») of players from the two national teams who play for the same club.

**Architecture:** A new memoized SPARQL query in `app/kg.py` returns every called-up player with their club. A new `app/duell.py` joins that against the two canonical teams of each match (KG English label → canonical via `teams.canonical`) to produce shared-club «duells». `app/main.py` attaches the result as a `duell` field on each match view during the normal `rebuild_state`. The frontend (`kik.js`) mounts a dependency-free canvas force-sim inside the expanded card.

**Tech Stack:** Python 3.12, rdflib (SPARQL over Turtle), FastAPI, vanilla JS + Canvas 2D. No test framework in this repo — verification is via the build venv (`wc2026-kg/.venv`) for backend modules and the running app for the frontend.

---

## Conventions for this plan

- **No pytest.** This repo has no test suite. Backend "tests" are throwaway verification scripts run with the build venv:
  `PYTHONPATH=. wc2026-kg/.venv/bin/python - <<'EOF' … EOF` from the repo root.
- Code, comments, and log messages are **Norwegian** (match the codebase).
- Commit after each task.

## File structure

- **Modify** `app/kg.py` — add memoized `club_rosters()` (one SPARQL query, cached).
- **Create** `app/duell.py` — `build_index()` + `for_match(m, index)`; depends only on `kg` + `teams`.
- **Modify** `app/main.py` — import `duell`; `_match_view` gains `id` + `duell`; `rebuild_state` builds the index once and passes it in.
- **Create** `app/static/kik.js` — multi-instance canvas force-sim; exposes `window.mountKik`.
- **Modify** `app/static/app.js` — `matchCard` renders the kik block + becomes clickable on duell; `toggleMatch` mounts/stops the sim; a `DUELL` map caches payloads per match id.
- **Modify** `app/static/index.html` — load `kik.js` before `app.js`.
- **Modify** `app/static/style.css` — styles for `.kik` / `.kik-canvas` (mirror `.match-details` show-on-open).

---

### Task 1: `club_rosters()` in `app/kg.py`

**Files:**
- Modify: `app/kg.py` (append after `full_graph()`)

- [ ] **Step 1: Write the verification script (expect failure)**

Create `/tmp/check_rosters.py`:

```python
from app import kg
rows = kg.club_rosters()
assert len(rows) > 1000, f"forventet >1000 rader, fikk {len(rows)}"
sample = rows[0]
assert set(sample) == {"team_label", "club", "club_label", "player_name", "value"}, sample
# memoisering: andre kall returnerer samme objekt
assert kg.club_rosters() is rows, "club_rosters skal være memoisert"
# Doku spiller for Man City
city = [r for r in rows if "Doku" in r["player_name"]]
assert city and "City" in city[0]["club_label"], city
print(f"OK: {len(rows)} rader, Doku → {city[0]['club_label']}")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `PYTHONPATH=. wc2026-kg/.venv/bin/python /tmp/check_rosters.py`
Expected: FAIL — `AttributeError: module 'app.kg' has no attribute 'club_rosters'`

- [ ] **Step 3: Implement `club_rosters()`**

Append to `app/kg.py` (uses existing `_PREFIXES`, `_num`, `_load`, `_lock`):

```python
_club_roster = None  # memoisert: liste av {team_label, club, club_label, player_name, value}


def club_rosters():
    """Alle opptatte spillere som har en klubb, som flate rader til «Kamp i
    kampen»-duellene. Memoisert – grafen er statisk, så SPARQL kjøres bare én
    gang i prosessens levetid (grafen lastes uansett ved oppstart)."""
    global _club_roster
    if _club_roster is not None:
        return _club_roster
    g = _load()
    q = _PREFIXES + """
    SELECT ?teamLabel ?club ?clubLabel ?playerName ?mv WHERE {
      ?team a wc:NationalTeam ; rdfs:label ?teamLabel ; wc:calledUp ?player .
      ?player foaf:name ?playerName ; wc:playsAtClub ?club .
      ?club rdfs:label ?clubLabel .
      OPTIONAL { ?player wc:marketValueEUR ?mv }
    }
    """
    with _lock:
        rows = list(g.query(q))
    _club_roster = [
        {
            "team_label": str(r.teamLabel),
            "club": str(r.club),
            "club_label": str(r.clubLabel),
            "player_name": str(r.playerName),
            "value": _num(r.mv),
        }
        for r in rows
    ]
    return _club_roster
```

- [ ] **Step 4: Run the verification script — expect PASS**

Run: `PYTHONPATH=. wc2026-kg/.venv/bin/python /tmp/check_rosters.py`
Expected: `OK: 1248 rader, Doku → Manchester City` (row count may vary slightly)

- [ ] **Step 5: Commit**

```bash
git add app/kg.py
git commit -m "KG: club_rosters() – memoisert spillere-med-klubb spørring for kamp-i-kampen

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `app/duell.py` — match join

**Files:**
- Create: `app/duell.py`

- [ ] **Step 1: Write the verification script (expect failure)**

Create `/tmp/check_duell.py`:

```python
from app import duell
idx = duell.build_index()
assert idx, "indeksen skal ikke være tom (KG tilgjengelig)"

# Belgia–Egypt → Manchester City med Doku (hjemme) og Marmoush (borte)
m = {"home": "Belgium", "away": "Egypt"}
clubs = duell.for_match(m, idx)
assert clubs, "forventet minst én felles klubb for Belgia–Egypt"
city = [c for c in clubs if "City" in c["club"]]
assert city, [c["club"] for c in clubs]
home_names = {p["name"] for p in city[0]["home"]}
away_names = {p["name"] for p in city[0]["away"]}
assert any("Doku" in n for n in home_names), home_names
assert any("Marmoush" in n for n in away_names), away_names

# Lag uten felles klubb → None
assert duell.for_match({"home": "Norway", "away": "Brazil"}, idx) is None or \
       isinstance(duell.for_match({"home": "Norway", "away": "Brazil"}, idx), list)

# Tom indeks → None
assert duell.for_match(m, {}) is None
print("OK:", city[0]["club"], sorted(home_names), "vs", sorted(away_names))
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `PYTHONPATH=. wc2026-kg/.venv/bin/python /tmp/check_duell.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.duell'`

- [ ] **Step 3: Create `app/duell.py`**

```python
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
```

- [ ] **Step 4: Run the verification script — expect PASS**

Run: `PYTHONPATH=. wc2026-kg/.venv/bin/python /tmp/check_duell.py`
Expected: `OK: Manchester City ['Jérémy Doku'] vs ['Omar Marmoush']` (names may vary with squad data)

- [ ] **Step 5: Commit**

```bash
git add app/duell.py
git commit -m "Duell: join KG-klubber mot kampens to lag (kamp-i-kampen)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Wire `duell` into match views (`app/main.py`)

**Files:**
- Modify: `app/main.py` — import (line ~17), `_match_view` (lines 45-62), `rebuild_state` (lines 65-99)

- [ ] **Step 1: Add the import**

Add near the other `from . import …` lines (after `from . import kg`):

```python
from . import duell as duell_mod
```

- [ ] **Step 2: Extend `_match_view`**

Replace the `_match_view` signature and body (lines 45-62) so it accepts the index and emits `id` + `duell`:

```python
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
        "highlights": highlights_view((highlights or {}).get(match_key(m))),
        "report_url": nrk_url(m, nrk),
        "duell": duell_mod.for_match(m, duell_index) if duell_index else None,
    }
```

- [ ] **Step 3: Build the index once in `rebuild_state` and pass it in**

In `rebuild_state`, after `news = build_news()` (line 84) add:

```python
    # «Kamp i kampen»: felles klubblag pr kamp (KG). Indeksen bygges én gang her;
    # kg.club_rosters() er memoisert, så dette koster ingen SPARQL etter oppstart.
    duell_index = duell_mod.build_index()
```

Then update the three `_match_view` calls in the `"matches"` dict (lines 96-98) to:

```python
            "matches": {
                "live": [_match_view(m, duell_index=duell_index) for m in live],
                "finished": [
                    _match_view(m, highlights, nrk_links, duell_index)
                    for m in finished[-12:]
                ][::-1],
                "upcoming": [_match_view(m, duell_index=duell_index) for m in upcoming],
            },
```

- [ ] **Step 4: Verify the app boots and serves `duell`**

Start the app (demo data is fine; it just yields empty duells), then confirm the field exists and JSON is well-formed:

```bash
PREDICTIONS_XLSX=data/svar.xlsx FASIT_JSON=data/fasit.json \
  uvicorn app.main:app --port 8000 &
sleep 4
curl -s localhost:8000/api/state | python3 -c "import sys,json; s=json.load(sys.stdin); ms=s['matches']['live']+s['matches']['finished']+s['matches']['upcoming']; print('matches:', len(ms)); print('alle har id+duell-nøkkel:', all('id' in m and 'duell' in m for m in ms))"
kill %1
```

Expected: prints the match count and `alle har id+duell-nøkkel: True`. (With demo/no-token data, `duell` values are `None` — real WC data populates them.)

- [ ] **Step 5: Commit**

```bash
git add app/main.py
git commit -m "Main: legg id + duell på kampvisningen, bygg duell-indeks pr refresh

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Frontend node graph (`app/static/kik.js`)

**Files:**
- Create: `app/static/kik.js`
- Modify: `app/static/index.html:119` (add script tag before `app.js`)

- [ ] **Step 1: Create `app/static/kik.js`**

```javascript
"use strict";
// «Kamp i kampen»: liten, avhengighetsfri force-directed nodegraf pr kampkort.
// Spillere fra de to landslagene som deler klubblag, knyttet gjennom en klubb-hub.
// Fler-instans: window.mountKik(canvas, duell, homeFlag, awayFlag) → { stop() }.

(function () {
  const COL = { club: "#60a5fa", home: "#fbbf24", away: "#4ade80" };

  function buildGraph(duell, homeFlag, awayFlag) {
    const nodes = [];
    const links = [];
    let i = 0;
    for (const c of duell) {
      const hub = { id: "c" + i++, type: "club", label: c.club };
      nodes.push(hub);
      const addSide = (players, side, flag) => {
        for (const p of players) {
          const n = { id: "p" + i++, type: side, label: p.name, flag };
          nodes.push(n);
          links.push({ s: hub, t: n });
        }
      };
      addSide(c.home, "home", homeFlag);
      addSide(c.away, "away", awayFlag);
    }
    return { nodes, links };
  }

  // Enkel fysikk: frastøtning mellom alle noder + fjær langs lenker + sentrering.
  function step(nodes, links, w, h) {
    for (let a = 0; a < nodes.length; a++) {
      for (let b = a + 1; b < nodes.length; b++) {
        const na = nodes[a], nb = nodes[b];
        let dx = na.x - nb.x, dy = na.y - nb.y;
        let d2 = dx * dx + dy * dy || 0.01;
        const d = Math.sqrt(d2), f = 1400 / d2;
        const ux = dx / d, uy = dy / d;
        na.vx += ux * f; na.vy += uy * f;
        nb.vx -= ux * f; nb.vy -= uy * f;
      }
    }
    for (const l of links) {
      let dx = l.t.x - l.s.x, dy = l.t.y - l.s.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = (d - 78) * 0.012, ux = dx / d, uy = dy / d;
      l.s.vx += ux * f; l.s.vy += uy * f;
      l.t.vx -= ux * f; l.t.vy -= uy * f;
    }
    for (const n of nodes) {
      n.vx += (w / 2 - n.x) * 0.012;
      n.vy += (h / 2 - n.y) * 0.012;
      n.vx *= 0.85; n.vy *= 0.85;
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(46, Math.min(w - 46, n.x));
      n.y = Math.max(22, Math.min(h - 16, n.y));
    }
  }

  function mountKik(canvas, duell, homeFlag, awayFlag) {
    const { nodes, links } = buildGraph(duell, homeFlag, awayFlag);
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 260;
    const h = Math.max(150, 56 + nodes.length * 13);
    canvas.style.height = h + "px";
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);
    nodes.forEach((n, idx) => {
      const a = (idx / nodes.length) * Math.PI * 2;
      n.x = w / 2 + Math.cos(a) * 52;
      n.y = h / 2 + Math.sin(a) * 38;
      n.vx = 0; n.vy = 0;
    });

    let running = true, frame = 0;
    function draw() {
      if (!running) return;
      step(nodes, links, w, h);
      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = "rgba(255,255,255,0.18)";
      ctx.lineWidth = 1.2;
      for (const l of links) {
        ctx.beginPath();
        ctx.moveTo(l.s.x, l.s.y);
        ctx.lineTo(l.t.x, l.t.y);
        ctx.stroke();
      }
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      for (const n of nodes) {
        const r = n.type === "club" ? 7 : 5;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fillStyle = COL[n.type];
        ctx.fill();
        ctx.font = n.type === "club" ? "600 12px system-ui" : "11px system-ui";
        ctx.fillStyle = "#e8f0e8";
        const txt =
          n.type === "club" ? n.label : (n.flag ? n.flag + " " : "") + n.label;
        ctx.fillText(txt, n.x, n.y - r - 7);
      }
      if (++frame < 600) requestAnimationFrame(draw);
    }
    requestAnimationFrame(draw);
    return { stop() { running = false; } };
  }

  window.mountKik = mountKik;
})();
```

- [ ] **Step 2: Load it before `app.js`**

In `app/static/index.html`, replace line 119:

```html
<script src="/static/app.js"></script>
```

with:

```html
<script src="/static/kik.js"></script>
<script src="/static/app.js"></script>
```

- [ ] **Step 3: Verify the script loads with no console error**

With the app running (`uvicorn app.main:app --port 8000`), open `http://localhost:8000/` and in the browser console run:

```js
typeof window.mountKik
```

Expected: `"function"` and no 404 for `/static/kik.js` in the Network tab.

- [ ] **Step 4: Commit**

```bash
git add app/static/kik.js app/static/index.html
git commit -m "Frontend: kik.js – fler-instans force-graf for kamp-i-kampen

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Wire the graph into the match cards (`app/static/app.js` + CSS)

**Files:**
- Modify: `app/static/app.js` — `matchCard` (lines 60-77); add `DUELL` map + `toggleMatch` helper near the top.
- Modify: `app/static/style.css` — append `.kik` rules.

- [ ] **Step 1: Add the duell cache + toggle handler**

In `app/static/app.js`, immediately after the `const $ = …` line (line 3), add:

```javascript
// «Kamp i kampen»: payload pr kamp-id (kortene re-rendres hvert 60 s, så vi
// holder duell-dataene utenfor DOM-en) + aktive sim-håndtak pr kort-element.
const DUELL = new Map();
const _kikHandles = new WeakMap();

function toggleMatch(card) {
  const open = card.classList.toggle("open");
  const canvas = card.querySelector(".kik-canvas");
  if (!canvas) return;
  if (open) {
    const d = DUELL.get(card.dataset.mid);
    if (d && !_kikHandles.has(card)) {
      _kikHandles.set(card, window.mountKik(canvas, d.duell, d.homeFlag, d.awayFlag));
    }
  } else {
    const h = _kikHandles.get(card);
    if (h) { h.stop(); _kikHandles.delete(card); }
  }
}
window.toggleMatch = toggleMatch;
```

- [ ] **Step 2: Render the kik block in `matchCard`**

In `app/static/app.js`, replace the whole `matchCard` function (lines 60-77) with:

```javascript
function kikBlock(m) {
  if (!m.duell || !m.duell.length) return "";
  return `<div class="kik"><h4>🔗 Kamp i kampen</h4><canvas class="kik-canvas"></canvas></div>`;
}

function matchCard(m, live) {
  const played = m.goals_home !== null && m.goals_home !== undefined;
  const score = played
    ? `${m.goals_home}–${m.goals_away}`
    : new Date(m.date).toLocaleTimeString("no-NO", { hour: "2-digit", minute: "2-digit" });
  const inner = highlightsBlock(m.highlights) + reportBlock(m.report_url) + kikBlock(m);
  const expandable = inner.length > 0;
  if (m.duell && m.duell.length) {
    DUELL.set(m.id, { duell: m.duell, homeFlag: m.home_flag, awayFlag: m.away_flag });
  }
  const cls = `match ${live ? "live" : ""}${expandable ? " clickable" : ""}`;
  const onclick = expandable ? ' onclick="toggleMatch(this)"' : "";
  return `
    <div class="${cls}"${onclick} data-mid="${m.id}">
      <div class="team"><span>${m.home_flag}</span><span class="name">${m.home}</span></div>
      <div class="score">${score}</div>
      <div class="team away"><span class="name">${m.away}</span><span>${m.away_flag}</span></div>
      <div class="when">${fmtDate(m.date)} · ${stageBadge(m)}${m.pens ? " · " + m.pens : ""}${live ? " · PÅGÅR" : ""}${expandable ? " · 👆 detaljer" : ""}</div>
      ${inner}
    </div>`;
}
```

- [ ] **Step 3: Add the CSS**

Append to `app/static/style.css`:

```css
.kik {
    grid-column: 1 / -1;
    display: none;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--line);
}
.match.open .kik {
    display: block;
}
.kik h4 {
    margin: 0 0 4px;
    font-size: 0.7rem;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 600;
}
.kik-canvas {
    display: block;
    width: 100%;
}
```

- [ ] **Step 4: Verify end-to-end against real data**

The duell field is only populated when both teams are real WC teams (KG has them). Demo data won't show duells, so verify against a `FOOTBALL_DATA_TOKEN`-backed run (or temporarily craft state). With a token set and the app running:

1. Open `http://localhost:8000/`.
2. Find a group-stage match between two teams that share a club (e.g. Belgia–Egypt) in «Pågår nå» or the timeline strip.
3. Click the card → it expands and shows «🔗 Kamp i kampen» with an animated graph: a club hub node linking a yellow home-player node and a green away-player node (with flags + names).
4. Click again → it collapses and the animation stops (no runaway `requestAnimationFrame`).
5. A match with no shared club shows no «Kamp i kampen» section.

If no token is available, do a minimal data check instead — confirm a known matchup would produce a duell:

```bash
PYTHONPATH=. wc2026-kg/.venv/bin/python - <<'EOF'
from app import duell
idx = duell.build_index()
print(duell.for_match({"home": "Belgium", "away": "Egypt"}, idx))
EOF
```

Expected: a list containing `Manchester City` with Doku (home) and Marmoush (away) — proving the data the frontend will render.

- [ ] **Step 5: Commit**

```bash
git add app/static/app.js app/static/style.css
git commit -m "Frontend: vis kamp-i-kampen-graf i utvidet kampkort

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage:** club query (Task 1) ✓, canonical join + empty→None (Task 2) ✓, `id`+`duell` on match view & precompute-once (Task 3) ✓, mini force-graph inside expanded card (Tasks 4-5) ✓, hide-when-empty (Task 5 `kikBlock` returns "") ✓, demo yields no duell (Task 3 Step 4) ✓.
- **Refinement vs spec:** join logic lives in `app/duell.py` (not inline in `main.py`) for isolated testability — noted to the user.
- **Type consistency:** roster dict keys `{team_label, club, club_label, player_name, value}` (Task 1) are consumed verbatim in Task 2; `for_match` returns `[{club, home, away}]` consumed by `kikBlock`/`mountKik` (Tasks 4-5); `match_key` already imported in `main.py`.
- **`data-mid` safety:** `match_key` = `"<date>|<canon a>|<canon b>"`; no canonical name contains `"`/`'`, so the value is safe in the double-quoted HTML attribute.

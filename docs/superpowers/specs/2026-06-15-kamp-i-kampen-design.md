# «Kamp i kampen» — felles-klubb-duell i kampkortene

## Mål

Når en bruker klikker på en kamp i kampoversikten, utvides kortet og en seksjon
**«Kamp i kampen»** vises. Seksjonen er en liten force-directed nodegraf over
spillerne fra de to landslagene som spiller på samme klubblag. Eksempel
Belgia–Egypt: Doku (Belgia) og Marmoush (Egypt) spiller begge for Manchester
City → de to spillernodene knyttes sammen gjennom en klubb-node «Manchester
City».

Datakilden er kunnskapsgrafen i `wc2026-kg/wc2026.ttl` (samme graf som
`/graf`-utforskeren bruker). Funksjonen deler ingen tilstand med betting-appens
øvrige logikk utover ett nytt felt på kampvisningen.

## Datamodell i grafen (verifisert)

- Hvert landslag: `?team a wc:NationalTeam ; rdfs:label "<engelsk navn>"@en ;
  wc:calledUp ?player`.
- Hver spiller: `?player foaf:name ?name ; wc:playsAtClub ?club`
  (`wc:marketValueEUR` valgfri).
- Hver klubb: `?club rdfs:label "<klubbnavn>"@en`.

KG-ens engelske landslags-`rdfs:label` mapper rent tilbake til appens kanoniske
lagnavn via `teams.canonical()` (alias-indeksen håndterer «United States»→«USA»,
«Turkey»→«Türkiye», «Curacao»→«Curaçao», «Czech Republic»→«Czechia» osv.). Det
er join-nøkkelen mellom KG og kampdataene.

## Arkitektur

Tre lag, ingen nytt endepunkt, ingen database, ingen endring i refresh-/state-
flyten utover ett nytt felt.

### 1. `app/kg.py` — `club_rosters()`

Ny **memoisert** funksjon kjører én SPARQL-spørring over hele grafen:

```sparql
SELECT ?teamLabel ?club ?clubLabel ?playerName ?mv WHERE {
  ?team a wc:NationalTeam ; rdfs:label ?teamLabel ; wc:calledUp ?player .
  ?player foaf:name ?playerName ; wc:playsAtClub ?club .
  ?club rdfs:label ?clubLabel .
  OPTIONAL { ?player wc:marketValueEUR ?mv }
}
```

- Returnerer én rad pr opptatt spiller som har klubb (~1200 rader) som en liste
  av dicts: `{team_label, club, club_label, player_name, value}`.
- Resultatet caches i en modul-global (`_club_roster`). Grafen er statisk, så
  spørringen kjøres bare **én gang** i prosessens levetid. KG lastes uansett ved
  oppstart via `lifespan → kg._load`.
- Kjøres under den eksisterende `_lock` (pyparsing-tråd-trygghet), som resten av
  `kg.py`.

### 2. `app/main.py` — join pr kamp

En hjelpefunksjon bygger en indeks `club_uri → {kanonisk_lag → [spillere]}` fra
`club_rosters()`, der hver KG-label mappes via `teams.canonical()` (rader som
ikke mapper til et kjent lag hoppes over). For hver kamp gjøres et snitt på de to
kanoniske lagene `m["home"]` / `m["away"]`: hver klubb der **begge** lag har ≥1
spiller blir en «duell».

`_match_view(m, …)` får to nye felt:

- `id`: `match_key(m)` — stabil pr kamp på tvers av refresh (brukes som nøkkel i
  frontend-cachen).
- `duell`: liste, eller utelatt/`None` når tom:

```json
"duell": [
  {
    "club": "Manchester City",
    "home": [{"name": "Jérémy Doku", "value": 60000000}],
    "away": [{"name": "Omar Marmoush", "value": 75000000}]
  }
]
```

`duell` er `None`/utelatt når KG er utilgjengelig (`kg.available()` false),
laget ikke finnes i KG (demo-/placeholder-lag), eller ingen felles klubb finnes
→ seksjonen skjules.

Indeksbyggingen pr refresh er ren in-memory-iterasjon over ~1200 cachede rader;
ingen SPARQL kjøres etter første gang.

### 3. Frontend — `app/static/kik.js` (+ stil i `style.css`)

- `matchCard` (i `app.js`) blir klikkbar når kortet har **høydepunkter eller**
  en `duell`. Den eksisterende `onclick="this.classList.toggle('open')"` byttes
  til et kall som både toggler `open` og lazy-monterer grafen.
- Hvert kort med `duell` får et `Kamp i kampen`-blokk med et `<canvas>` i den
  utvidbare delen.
- En kompakt, avhengighetsfri canvas-force-sim (samme ånd som `kg-graph.js`, men
  fler-instans og selvstendig): **klubb-hub-node** i midten, **hjemmespiller-
  noder** tintet med hjemmeflagget på én side, **bortespiller-noder** med
  borteflagget på den andre, lenker hub↔spiller. Flere felles klubber = flere
  hub-er i samme graf.
- Lazy + billig: simet monteres først når kortet åpnes; `requestAnimationFrame`
  stoppes når kortet lukkes. Siden kortene re-rendres hvert 60 s, holdes hver
  kamps `duell`-payload i en JS-`Map` med `id` som nøkkel, fylt på hver refresh.
- Tom-tilfellet skjules (ingen seksjon).

## Visuell skisse

```
        Kamp i kampen
   🇧🇪 Doku ●──────● Manchester City ●──────● Marmoush 🇪🇬
            (hjem)        (klubb-hub)         (borte)
```

## Ikke-mål / YAGNI

- Ingen nytt API-endepunkt (data følger med `/api/state`).
- Ingen endring i scoring, fasit eller gruppe-/leaderboard-logikk.
- Ingen gjenbruk/omskriving av `kg-graph.js` (IIFE bundet til ett canvas) — den
  lille grafen er en separat, fler-instans implementasjon.
- `DemoProvider` gir ingen duell (placeholder-lag finnes ikke i KG) — det er ok.

## Test / verifisering

Ingen testsuite i repoet. Verifiseres mot kjørende app:

- `GET /api/state` → kontroller at minst én pågående/ferdig kamp med to ekte lag
  har et ikke-tomt `duell`-felt med forventede spillere (f.eks. Belgia–Egypt →
  Manchester City: Doku/Marmoush).
- `GET /` → klikk en slik kamp, bekreft at «Kamp i kampen»-grafen tegnes og
  animeres, og at et kort uten felles klubb ikke får seksjonen.

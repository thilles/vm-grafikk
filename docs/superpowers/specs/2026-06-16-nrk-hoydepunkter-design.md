# Kamphøydepunkter fra NRK/NIFS (erstatter api-sports)

**Dato:** 2026-06-16
**Status:** Godkjent design, klar for plan

## Bakgrunn og mål

api-sports' gratisplan er ikke brukbar (suspenderte konti / kvote), så dagens
kilde for kamphøydepunkter (mål + kort på ferdige kamper) faller bort. NRKs
resultatsider (`resultater.nrk.no`) kjører på NTBs NIFS-data — det samme åpne,
nøkkelfrie API-et (`api.nifs.no`) som `nrk_links.py` allerede bruker. NIFS gir
rikere hendelsesdata enn api-sports: mål, kort, assists, bytter **og** NRK-
videoklipp per hendelse.

Eksempel-URL fra brukeren (Haiti–Skottland):
`https://resultater.nrk.no/fotball/2026-06-14/1/events/2536540` — der `2536540`
er NIFS-kamp-id-en.

**Mål:**
1. Bytt høydepunkt-kilden fra api-sports til NIFS (mål + kort).
2. Legg til innebygd NRK-videoklipp per **mål**, spillbart i en modal på app-siden.
3. Vis høydepunktene som en **vertikal tidslinje** (hjemmelag venstre, bortelag
   høyre) i stedet for dagens grupperte mål-/kort-kolonner.

## Datakilde: NIFS matchEvents

`GET https://api.nifs.no/matches/<id>/` returnerer hele kampobjektet, inkl. en
`matchEvents`-liste. Relevante `matchEventTypeId`:

| id | betydning            | brukes |
|----|----------------------|--------|
| 1  | kommentar (live)     | nei    |
| 2  | mål                  | ja     |
| 4  | gult kort            | ja     |
| 5  | rødt kort (antatt)   | ja     |
| 48 | assist               | nei (foreløpig) |
| 23/24 | bytte ut/inn      | nei    |

Hver hendelse har: `team.name`, `person.name`, `time` (minutt) + `overtime`
(tilleggstid → `45+4`), og evt. `videos: [{source:"NRK", url:"<uuid>"}]`.

**Må verifiseres i implementasjon (kun normal-mål + gult kort fantes i
eksempelkampen):** type-id for selvmål, straffemål, rødt kort og gult-gult→rødt.
Hentes fra en reell kamp med slike hendelser, eller fra NIFS-data underveis.
`type`-feltet på mål skal være kompatibelt med dagens frontend:
`"normal" | "penalty" | "own"`.

## Videoavspilling: NRK psapi

`GET https://psapi.nrk.no/playback/manifest/clip/<uuid>` →
`playable.assets[].url` = ukryptert HLS `.m3u8`. Manifestet inneholder også
`availability.externalEmbeddingAllowed: true` og `availability.isGeoBlocked:
true` (Norge). Klippene kan altså bygges inn i appen, men er geoblokkert —
greit for en intern norsk konkurranse; «se hos NRK»-lenken er fallback.

## Arkitektur

### Backend

**`app/highlights.py` (omskriving):**
- Fjern alt api-sports-spesifikt (`BASE`, `WC_LEAGUE_ID`, `APISPORTS_*`,
  `_fixture_ids_for_date`, x-apisports-key).
- `build_highlights(matches, links)` tar inn NRK-lenkekartet (`pair_key →
  [{id,date}]`) fra `nrk_links.build_links`. For hver `FINISHED`-kamp uten
  cachede hendelser: finn NIFS-id via `links`, `GET /matches/<id>/`, normaliser
  hendelsene, cache (in-memory + fil, uforanderlig).
- Behold `match_key`, cache-formen `{match_key: {goals, cards}}`, og en moderat
  per-oppdatering-grense (NIFS er nøkkelfri, men det er høflig).
- Mål-hendelse: `{team, player, minute, type, video}` (video = klipp-uuid eller
  None). Kort: `{team, player, minute, card}` (uten video — valg: kun mål får
  klipp).
- `view(hl, home_canon, away_canon)` beriker med flagg/norsk navn **og** tagger
  hver hendelse med `side: "home"|"away"` (sammenlign kanonisk lag mot kampens
  hjemme/borte). Mål beholder `video`-uuid.

**`app/main.py`:**
- Flytt `build_links(finished)` foran `build_highlights`; send lenkekartet inn:
  `build_highlights(matches, nrk_links)`.
- `_match_view` sender kampens hjemme/borte-kanoniske navn til `highlights_view`.
- Nytt endepunkt `GET /api/highlights/clip/{uuid}`: kaller psapi server-side,
  returnerer `{m3u8, playable, geoBlocked}` (eller 404/502 ved feil). Holder
  NRK-API-kall på serveren og unngår CORS.

**`app/football_api.py`:** `DemoProvider`-høydepunktene får `video`- og
implisitt side-felt slik at demo-UI fortsatt fungerer offline (video=None →
ikke-klikkbart mål er greit).

### Frontend

**`app/static/app.js`:**
- Erstatt `highlightsBlock` med en **vertikal tidslinje**: én sentral loddrett
  linje, «Start» øverst og «Slutt» nederst. Alle hendelser (mål+kort) slås
  sammen og sorteres stigende på minutt. `side==="home"` → venstre kolonne,
  `side==="away"` → høyre.
- Rad: ikon (⚽/🟨/🟥) + minutt + flagg + spiller (+ «(selvmål)»/«(str)» som i
  dag). Mål med `video` får et ▶-element/klikkbar rad som åpner video-modalen.
- Video-modal: hent `/api/highlights/clip/<uuid>`, spill `m3u8` i `<video>` via
  hls.js (Safari: native HLS uten hls.js). Lukkeknapp. Hvis `!playable` eller
  geoblokkert: vis melding + lenke til NRK.
- Behold dagens «Se høydepunkter og rapport hos NRK»-lenke under tidslinjen som
  fallback (full reel / geoblokk-tilfeller).

**`app/static/index.html`:** legg til modal-container og
`<script src="https://cdn.jsdelivr.net/npm/hls.js@1/dist/hls.min.js">` (CDN-
valg; Safari trenger den ikke, men Chrome/Firefox gjør).

**`app/static/style.css`:** stiler for tidslinjen (sentral linje, venstre/høyre-
kolonner, ikoner) og video-modalen (overlay, `<video>`, lukkeknapp).

### Dokumentasjon

`CLAUDE.md` og `README`: bytt api-sports-omtalen til NRK/NIFS; fjern
`APISPORTS_*`-env-variablene; beskriv det nye klipp-endepunktet og tidslinjen.

## Dataflyt (per oppdatering)

1. `build_links(finished)` → `pair_key → [{id, date}]` (NIFS, cachet).
2. `build_highlights(matches, links)` → for hver ny ferdig kamp: NIFS-id fra
   `links` → `GET /matches/<id>/` → normaliser → cache. Returnerer
   `{match_key: {goals, cards}}`.
3. `_match_view` → `highlights_view(hl, home, away)` → tidslinje-data m/ side +
   video-uuid per mål.
4. Frontend tegner tidslinje; klikk på mål → `GET /api/highlights/clip/<uuid>` →
   hls.js spiller i modal.

## Avgrensninger (YAGNI)

- **Kun ferdige kamper** får høydepunkter (som i dag). Live-hendelser er ikke i
  scope (uforanderlighet/cache-antakelsen holder bare når `FINISHED`).
- **Kun mål** får videoklipp; kort vises som ren tekst.
- **Assists/bytter** tas ikke med nå (tilgjengelig i NIFS, kan legges til senere).
- Ingen ny env-variabel kreves (NIFS og psapi er nøkkelfrie).

## Åpne punkter å verifisere under implementasjon

1. NIFS `matchEventTypeId` for selvmål, straffemål, rødt kort, gult-gult→rødt.
2. CORS fra nettleser mot Akamai-HLS-segmentene (psapi proxes server-side; hvis
   `.m3u8`/segmenter også blokkeres av CORS, vurder server-side proxy — men
   `resultater.nrk.no`-SPA-en gjør nettopp dette fra nettleser, så trolig greit).
3. At hls.js fra CDN laster og spiller geoblokkert klipp fra norsk IP.

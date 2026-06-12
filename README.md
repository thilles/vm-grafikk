# D&I Tippekonkurranse VM 2026 – Scoreboard

Webapp som etter hver kamp henter resultater fra internett, regner ut poeng for
alle deltakerne i tippekonkurransen og viser et grafisk scoreboard med
ledertavle, kampresultater, gruppetabeller og fakta/kuriositeter.

**🔴 Live:** <https://vm26-scores.onrender.com/>

(Gratis Render-instans – har den stått ubrukt en stund, tar første visning
~30–60 sekunder mens tjenesten våkner og henter ferske data.)

## Kom i gang

```bash
# 1. Legg svarfilen (nedlastet fra Google Sheets) i data/
cp "Svar tippekonkurranse.xlsx" data/svar.xlsx

# 2. Skaff gratis API-nøkkel: https://www.football-data.org/client/register
export FOOTBALL_DATA_TOKEN=din-nøkkel

# 3. (Valgfritt) Mål/kort pr kamp: gratis nøkkel fra https://www.api-football.com
export APISPORTS_KEY=din-api-football-nøkkel

# 4. Bygg og start
docker compose up --build -d
```

Åpne <http://localhost:8000>. Uten `FOOTBALL_DATA_TOKEN` kjører appen med
demodata, tydelig merket i appen. `APISPORTS_KEY` er helt valgfri – settes den
ikke, fungerer alt som før, bare uten kamphøydepunkter (se under).

## Datakilder

| Hva                                   | Kilde                                                                       | Konfigurasjon                          |
| ------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------- |
| Kampresultater, tabeller, toppscorere | [football-data.org](https://www.football-data.org) (gratisnivået dekker VM) | `FOOTBALL_DATA_TOKEN`                  |
| Mål/kort pr ferdig kamp (høydepunkter) | [api-sports](https://www.api-football.com) (gratisnivået dekker VM via `?date=`) | `APISPORTS_KEY`                   |
| Tippesvar                             | Google Sheet (live) eller lokal Excel-fil                                   | `SHEET_CSV_URL` eller `data/svar.xlsx` |
| Manuell fasit                         | `data/fasit.json`                                                           | se under                               |

**Live-kobling mot Google Sheet:** I regnearket: _Fil → Del → Publiser på
nettet → velg arket → CSV_, og sett lenken som `SHEET_CSV_URL` i miljøet
(f.eks. i en `.env`-fil ved siden av `docker-compose.yml`). Da plukkes nye/
endrede svar opp automatisk. Uten denne brukes `data/svar.xlsx`.

Appen oppdaterer seg selv hvert `REFRESH_MINUTES` minutt (standard 10), og
frontend laster på nytt hvert minutt. `POST /api/refresh` tvinger en
oppdatering umiddelbart.

**Kamphøydepunkter (mål/kort) – krever api-football:** Funksjonen er avhengig av
en gratis nøkkel fra [api-football / api-sports](https://www.api-football.com),
satt som `APISPORTS_KEY`. Da blir spilte kamper klikkbare i «Siste resultater»
og viser målscorere og gule/røde kort. Dataene hentes fra api-sports
(gratis: 100 kall/døgn) – fordi gratisplanen ikke gir tilgang via
`?league=&season=2026`, hentes fixture-id via `?date=` og hendelser via `?id=`.
Hendelser for ferdigspilte kamper er uforanderlige, så de hentes én gang pr kamp
og caches (`HIGHLIGHTS_CACHE`, standard `/data/highlights_cache.json`) – forbruket
blir noen få kall i døgnet.

> **Uten `APISPORTS_KEY`:** høydepunkt-funksjonen er helt deaktivert – kampene
> blir ikke klikkbare og ingen mål/kort vises. Det gjøres ingen api-sports-kall,
> og resten av appen (resultater, ledertavle, tabeller, fakta) fungerer akkurat
> som før. Nøkkelen er altså valgfri.

## Poengberegning

Automatisk fasit utledes fra kampdataene etter hvert som turneringen skrider
frem (gruppetabeller, sluttspillsoppsett, finale, toppscorerliste osv.).
Poengverdier følger skjemaet:

| Spørsmål                    | Poeng                          | Avgjøres                                   |
| --------------------------- | ------------------------------ | ------------------------------------------ |
| Rekkefølge per gruppe (A–L) | 4 (1 per riktig plassering\*)  | gruppespillet ferdig                       |
| Jevneste gruppe             | 4                              | gruppespillet ferdig                       |
| Hvor ryker Norge ut         | 5                              | når Norge er ute / verdensmester           |
| Scorer Haiti mål            | 3                              | første Haiti-mål, ellers når Haiti er ute  |
| Toppscorer                  | 5                              | foreløpig underveis, endelig etter finalen |
| Første hattrick             | 5                              | manuelt (`fasit.json`)                     |
| VM-vinner                   | 20                             | etter finalen                              |
| Taper av finalen            | 15                             | etter finalen                              |
| Semifinalister              | 4 per riktig lag               | når semifinalene er satt opp               |
| 4 navngitte kampresultater  | 4 per kamp (eksakt resultat\*) | etter hver kamp                            |
| Sverige til 8-delsfinale    | 4                              | når R16 er satt opp / Sverige ute          |
| Afrikansk lag i kvartfinale | 4                              | når kvartfinalene er satt opp              |
| Mål totalt i kvartfinalene  | 4                              | etter kvartfinalene                        |
| Gule kort Ryerson           | 4                              | manuelt (`fasit.json`)                     |
| Selvmål i semifinalene      | 4                              | manuelt (`fasit.json`)                     |

\* Antakelse – skjemaet sier bare totalpoeng. Reglene ligger samlet i
`app/scoring.py` og er enkle å justere (f.eks. «4 poeng kun ved helt riktig
gruppe» eller delpoeng for riktig utfall i kampresultat).

Foreløpige poeng (f.eks. toppscorer underveis) merkes med `*` i appen;
«sikre poeng» teller bare endelig avgjorte spørsmål.

### Manuell fasit – `data/fasit.json`

Tre spørsmål kan ikke hentes pålitelig fra gratis-API-et og settes manuelt av
arrangøren. Filen kan også overstyre alt annet ved behov:

```json
{
  "hattrick": "Haaland",
  "ryerson": 2,
  "selvmaal_semi": "Ja"
}
```

Se `data/fasit.example.json`. Endringer plukkes opp ved neste oppdatering.

## Gratis hosting på Render

Slik gjenskaper du oppsettet bak <https://vm26-scores.onrender.com/>:

1. **Fork/push dette repoet til GitHub** (privat repo fungerer fint).
   `.gitignore` holder `.env` (API-nøkkelen) og `data/svar.xlsx` utenfor.
2. Lag konto på [render.com](https://render.com) og velg
   **New → Web Service → Connect repository** og pek på repoet.
   Render oppdager `Dockerfile` automatisk – ingen build-innstillinger trengs
   (appen lytter på porten Render tildeler via `PORT`).
3. Velg **Free**-planen.
4. Under **Environment** legger du inn:
   | Variabel | Verdi |
   |---|---|
   | `FOOTBALL_DATA_TOKEN` | API-nøkkelen din fra football-data.org |
   | `SHEET_CSV_URL` | publisert CSV-lenke til Google Sheetet med svarene |

   `SHEET_CSV_URL` er i praksis påkrevd i skyen: der finnes ingen lokal
   `data/svar.xlsx` å falle tilbake på.
5. **Deploy.** Hver push til repoet utløser automatisk ny deploy.

Verdt å vite på gratisplanen:

- **Tjenesten sovner etter ~15 min uten trafikk** og bruker 30–60 sekunder på
  å våkne. Sett opp en gratis overvåker (f.eks. [uptimerobot.com](https://uptimerobot.com)
  eller [cron-job.org](https://cron-job.org)) som pinger `/api/state` hvert
  10. minutt, så holder den seg våken under turneringen.
- **Ingen vedvarende disk.** Manuell fasit kan derfor ikke legges i et volum –
  legg heller `data/fasit.json` inn i repoet (fjern linjen fra `.gitignore`)
  og push; `Dockerfile` kopierer `data/` inn i imaget, og hver push
  redeployer med oppdatert fasit.
- Siden blir offentlig tilgjengelig for alle som har URL-en (deltakernavn og
  tippesvar inkludert) – greit for en intern konkurranse, men verdt å vite.

## Drift uten docker compose

```bash
docker build -t vm-scoreboard .
docker run -d -p 8000:8000 -v "$PWD/data:/data" \
  -e FOOTBALL_DATA_TOKEN=din-nøkkel vm-scoreboard
```

## Struktur

```
app/
  main.py          FastAPI-app + bakgrunnsjobb
  football_api.py  football-data.org-klient + demodata
  highlights.py    api-sports-klient: mål/kort pr kamp + cache
  predictions.py   parser Google Forms-svarene (CSV/XLSX)
  scoring.py       fasit-utledning og poengberegning
  facts.py         fakta, kuriositeter og highlights
  teams.py         lagdatabase (navn, alias, flagg, grupper)
  static/          frontend (scoreboard)
```

Merk: gruppetabeller beregnes med poeng → målforskjell → scorede mål som
tiebreak. FIFAs fulle regelverk (innbyrdes oppgjør osv.) dekkes ikke, men
API-ets offisielle plasseringer vinner uansett når gruppene er ferdigspilte,
siden sluttspillsoppsettet hentes derfra.

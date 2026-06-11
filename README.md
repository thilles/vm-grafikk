# D&I Tippekonkurranse VM 2026 – Scoreboard

Webapp som etter hver kamp henter resultater fra internett, regner ut poeng for
alle deltakerne i tippekonkurransen og viser et grafisk scoreboard med
ledertavle, kampresultater, gruppetabeller og fakta/kuriositeter.

## Kom i gang

```bash
# 1. Legg svarfilen (nedlastet fra Google Sheets) i data/
cp "Svar tippekonkurranse.xlsx" data/svar.xlsx

# 2. Skaff gratis API-nøkkel: https://www.football-data.org/client/register
export FOOTBALL_DATA_TOKEN=din-nøkkel

# 3. Bygg og start
docker compose up --build -d
```

Åpne <http://localhost:8000>. Uten API-nøkkel kjører appen med demodata,
tydelig merket i appen.

## Datakilder

| Hva | Kilde | Konfigurasjon |
|---|---|---|
| Kampresultater, tabeller, toppscorere | [football-data.org](https://www.football-data.org) (gratisnivået dekker VM) | `FOOTBALL_DATA_TOKEN` |
| Tippesvar | Google Sheet (live) eller lokal Excel-fil | `SHEET_CSV_URL` eller `data/svar.xlsx` |
| Manuell fasit | `data/facit.json` | se under |

**Live-kobling mot Google Sheet:** I regnearket: *Fil → Del → Publiser på
nettet → velg arket → CSV*, og sett lenken som `SHEET_CSV_URL` i miljøet
(f.eks. i en `.env`-fil ved siden av `docker-compose.yml`). Da plukkes nye/
endrede svar opp automatisk. Uten denne brukes `data/svar.xlsx`.

Appen oppdaterer seg selv hvert `REFRESH_MINUTES` minutt (standard 10), og
frontend laster på nytt hvert minutt. `POST /api/refresh` tvinger en
oppdatering umiddelbart.

## Poengberegning

Automatisk fasit utledes fra kampdataene etter hvert som turneringen skrider
frem (gruppetabeller, sluttspillsoppsett, finale, toppscorerliste osv.).
Poengverdier følger skjemaet:

| Spørsmål | Poeng | Avgjøres |
|---|---|---|
| Rekkefølge per gruppe (A–L) | 4 (1 per riktig plassering*) | gruppespillet ferdig |
| Jevneste gruppe | 4 | gruppespillet ferdig |
| Hvor ryker Norge ut | 5 | når Norge er ute / verdensmester |
| Scorer Haiti mål | 3 | første Haiti-mål, ellers når Haiti er ute |
| Toppscorer | 5 | foreløpig underveis, endelig etter finalen |
| Første hattrick | 5 | manuelt (`facit.json`) |
| VM-vinner | 20 | etter finalen |
| Taper av finalen | 15 | etter finalen |
| Semifinalister | 4 per riktig lag | når semifinalene er satt opp |
| 4 navngitte kampresultater | 4 per kamp (eksakt resultat*) | etter hver kamp |
| Sverige til 8-delsfinale | 4 | når R16 er satt opp / Sverige ute |
| Afrikansk lag i kvartfinale | 4 | når kvartfinalene er satt opp |
| Mål totalt i kvartfinalene | 4 | etter kvartfinalene |
| Gule kort Ryerson | 4 | manuelt (`facit.json`) |
| Selvmål i semifinalene | 4 | manuelt (`facit.json`) |

\* Antakelse – skjemaet sier bare totalpoeng. Reglene ligger samlet i
`app/scoring.py` og er enkle å justere (f.eks. «4 poeng kun ved helt riktig
gruppe» eller delpoeng for riktig utfall i kampresultat).

Foreløpige poeng (f.eks. toppscorer underveis) merkes med `*` i appen;
«sikre poeng» teller bare endelig avgjorte spørsmål.

### Manuell fasit – `data/facit.json`

Tre spørsmål kan ikke hentes pålitelig fra gratis-API-et og settes manuelt av
arrangøren. Filen kan også overstyre alt annet ved behov:

```json
{
  "hattrick": "Haaland",
  "ryerson": 2,
  "selvmaal_semi": "Ja"
}
```

Se `data/facit.example.json`. Endringer plukkes opp ved neste oppdatering.

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

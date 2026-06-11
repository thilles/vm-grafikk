"""Fakta, kuriositeter og highlights – utledet fra kampdata og tippesvarene."""
import datetime
from collections import Counter

from .teams import display, no_name

# Kuriositeter per lag – vises når laget nylig har spilt / snart spiller
CURIOSITIES = {
    "Haiti": "Haiti er i VM for første gang siden 1974 – og spiller alle hjemmekampene sine på «bortebane»: laget har ikke kunnet spille i eget land på flere år.",
    "Curaçao": "Curaçao er med ~156 000 innbyggere den minste nasjonen som noensinne har kvalifisert seg til VM.",
    "Norway": "Norge er i VM for første gang siden Frankrike 1998 – den gang slo vi Brasil 2–1 i gruppespillet.",
    "Cape Verde": "Kapp Verde debuterer i VM – øystaten har færre innbyggere enn Oslo.",
    "Jordan": "Jordan spiller sitt aller første VM-sluttspill.",
    "Uzbekistan": "Usbekistan er VM-debutant etter å ha banket på døra i flere kvalifiseringer på rad.",
    "Scotland": "Skottland er tilbake i VM for første gang siden 1998 – samme år som Norge sist var med.",
    "Iraq": "Irak er i VM for første gang siden 1986.",
    "DR Congo": "DR Kongo er tilbake i VM for første gang siden 1974, den gang som Zaire.",
    "Canada": "Vertsnasjon Canada har aldri vunnet en VM-kamp – kan det endre seg på hjemmebane?",
    "Mexico": "Mexico er første land som arrangerer VM tre ganger (1970, 1986, 2026). Estadio Azteca er første stadion med tre VM-åpningskamper.",
    "USA": "USA arrangerte sist VM i 1994 – og snittet per kamp den gang er fortsatt tidenes høyeste VM-tilskuertall.",
    "New Zealand": "New Zealand er eneste lag som gikk ubeseiret gjennom VM 2010 (tre uavgjorte) – uten å gå videre fra gruppen.",
    "Panama": "Panama scoret sitt første VM-mål noensinne i 2018 – feiringen var som om de vant hele turneringen.",
    "Qatar": "Qatar er det eneste vertslandet i historien som har tapt åpningskampen i eget VM (2022).",
    "Argentina": "Argentina jakter sin fjerde tittel – og Messi kan bli den første som spiller seks VM-sluttspill.",
    "France": "Frankrike har vært i finalen i to av de tre siste VM – og Mbappé scoret hat trick i finalen i 2022.",
    "Brazil": "Brasil er eneste nasjon som har deltatt i samtlige VM-sluttspill – og fortsatt regjerende rekordholder med fem titler.",
    "Germany": "Tyskland har røket ut i gruppespillet i to VM på rad – tre på rad har aldri skjedd for en tidligere verdensmester.",
    "Spain": "Spania kan bli første lag som holder EM- og VM-tittelen samtidig siden Frankrike i 2000.",
    "England": "England har vunnet VM én gang – for 60 år siden i 1966. «It's coming home»?",
    "Morocco": "Marokko ble i 2022 første afrikanske lag i en VM-semifinale.",
    "Saudi Arabia": "Saudi-Arabia sto for tidenes kanskje største VM-sjokk da de slo senere verdensmester Argentina i 2022.",
}

TOURNAMENT_FACTS = [
    "VM 2026 er det første med 48 lag og 104 kamper – fordelt på 16 byer i tre land.",
    "For første gang går lag på tredjeplass i gruppene videre til en 16-delsfinale (runde med 32 lag).",
    "Finalen spilles på MetLife Stadium i New Jersey 19. juli 2026.",
    "Kampene spilles i tre tidssoner – tidlig kamp i Vancouver kan bety nattkamp i Norge.",
]


def _fmt_match(m):
    return f"{display(m['home'])} {m['goals_home']}–{m['goals_away']} {display(m['away'])}"


def build_facts(matches, people, demo):
    facts = []
    finished = [m for m in matches if m["status"] == "FINISHED"
                and m["goals_home"] is not None]

    # Statistikk fra spilte kamper
    if finished:
        total_goals = sum(m["goals_home"] + m["goals_away"] for m in finished)
        avg = total_goals / len(finished)
        facts.append({"icon": "⚽", "title": "Måltotalen",
                      "text": f"{total_goals} mål på {len(finished)} kamper – {avg:.2f} i snitt per kamp."})

        biggest = max(finished, key=lambda m: abs(m["goals_home"] - m["goals_away"]))
        if abs(biggest["goals_home"] - biggest["goals_away"]) >= 2:
            facts.append({"icon": "🔨", "title": "Største seier så langt", "text": _fmt_match(biggest)})

        wildest = max(finished, key=lambda m: m["goals_home"] + m["goals_away"])
        if wildest["goals_home"] + wildest["goals_away"] >= 3 and wildest is not biggest:
            facts.append({"icon": "🎢", "title": "Målrikeste kamp", "text": _fmt_match(wildest)})

        zeros = [m for m in finished if m["goals_home"] + m["goals_away"] == 0]
        if zeros:
            facts.append({"icon": "🥱", "title": "Målløst",
                          "text": f"{len(zeros)} kamp(er) har endt 0–0. Noen måtte jo tippe dem."})

    # Kuriositeter – utvalget roterer utover dagen (nytt utvalg hver 4. time),
    # med lag som spiller i dag / nylig har spilt først i køen.
    now = datetime.datetime.now()
    today = datetime.date.today().isoformat()
    relevant_teams = []
    for m in matches:
        if (m["utc_date"] or "").startswith(today) or m in finished[-4:]:
            relevant_teams += [m["home"], m["away"]]
    pool = []
    for t in relevant_teams + list(CURIOSITIES):
        if t in CURIOSITIES and t not in pool:
            pool.append(t)
    slot = now.toordinal() * 6 + now.hour // 4
    for i in range(min(3, len(pool))):
        t = pool[(slot + i) % len(pool)]
        facts.append({"icon": "💡", "title": f"Visste du? ({no_name(t)})", "text": CURIOSITIES[t]})

    # Moro fra tippesvarene
    if people:
        champs = Counter(p["vinner"] for p in people if p["vinner"])
        if champs:
            fav, cnt = champs.most_common(1)[0]
            facts.append({"icon": "🏆", "title": "Kontorets favoritt",
                          "text": f"{cnt} av {len(people)} tror {no_name(fav)} vinner VM."})
            unique = [no_name(t) for t, c in champs.items() if c == 1]
            if unique and len(unique) < len(champs):
                facts.append({"icon": "🃏", "title": "Alenegang",
                              "text": "Tippet vinner ingen andre tror på: " + ", ".join(unique) + "."})
        optimists = [p["name"] for p in people if p["norge_ut"] in ("Finale", "Vinner finalen", "Semifinale")]
        if optimists:
            facts.append({"icon": "🇳🇴", "title": "Norge-optimistene",
                          "text": ", ".join(optimists) + " tror Norge når semifinalen eller lenger!"})

    # Generelle turneringsfakta – roterer i samme takt som kuriositetene
    facts.append({"icon": "🌎", "title": "VM 2026", "text": TOURNAMENT_FACTS[slot % len(TOURNAMENT_FACTS)]})

    if demo:
        facts.insert(0, {"icon": "🧪", "title": "Demodata",
                         "text": "Appen kjører uten API-nøkkel og viser eksempeldata. Sett FOOTBALL_DATA_TOKEN for ekte resultater."})
    return facts

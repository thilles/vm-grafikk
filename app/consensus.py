"""«Kontoret stemte» – aggregerer deltakernes tipp på utvalgte nøkkelspørsmål."""
from collections import Counter

from .teams import flag, no_name

# Rekkefølge på alternativene for Norge slik de står i skjemaet
NORGE_ORDER = ["Gruppespill", "16-delsfinale", "8-delsfinale", "Kvartfinale",
               "Semifinale", "Finale", "Vinner finalen"]


def _tally(values, total, labeler=lambda x: x, flagger=lambda x: ""):
    """Teller opp og returnerer andeler sortert med flest stemmer først."""
    counts = Counter(v for v in values if v)
    return [
        {"label": labeler(val), "flag": flagger(val), "count": n,
         "pct": round(100 * n / total) if total else 0}
        for val, n in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))
    ]


def build_consensus(people):
    total = len(people)
    if not total:
        return []

    polls = []

    # Hvem vinner VM (kanoniske lagnavn -> flagg + norsk navn)
    polls.append({
        "icon": "🏆", "title": "Hvem vinner VM?",
        "options": _tally([p["vinner"] for p in people], total,
                          labeler=no_name, flagger=flag),
    })

    # Toppscorer (alternativtekst fra skjemaet)
    polls.append({
        "icon": "👟", "title": "Hvem blir toppscorer?",
        "options": _tally([p["toppscorer"] for p in people], total),
    })

    # Hvor langt går Norge – behold skjemaets rekkefølge
    norge = _tally([p["norge_ut"] for p in people], total)
    norge.sort(key=lambda o: NORGE_ORDER.index(o["label"]) if o["label"] in NORGE_ORDER else 99)
    polls.append({"icon": "🇳🇴", "title": "Hvor langt går Norge?", "options": norge})

    return polls

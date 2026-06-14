#!/usr/bin/env python3
"""Generate market_values.json — a STATIC, manually-curated snapshot of player
market values (EUR), used as an offline enrichment source when no live
Transfermarkt API is available.

Values are approximate Transfermarkt-style estimates for the start of 2026 and
are NOT live data (see README caveats). At least one player is provided per
nation so the "most valuable player per team" query returns all 48 teams.

The script matches curated full names against the parsed squad (cache/squads.json)
so the JSON keys equal the canonical player ids (slug(name)-yearOfBirth) used by
the graph builder. Run after build.py has populated the cache.
"""
import json
import os

from uris import slug

HERE = os.path.dirname(os.path.abspath(__file__))

# Curated full name -> market value in EUR (approximate, early-2026 snapshot).
CURATED = {
    # Group A
    "Patrik Schick": 30_000_000,
    "Santiago Giménez": 45_000_000,
    "Lyle Foster": 12_000_000,
    "Kim Min-jae": 45_000_000,
    # Group B
    "Amar Dedić": 22_000_000,
    "Alphonso Davies": 50_000_000,
    "Akram Afif": 8_000_000,
    "Manuel Akanji": 42_000_000,
    # Group C
    "Vinícius Júnior": 200_000_000,
    "Raphinha": 100_000_000,
    "Duckens Nazon": 1_000_000,
    "Achraf Hakimi": 65_000_000,
    "Scott McTominay": 30_000_000,
    # Group D
    "Connor Metcalfe": 8_000_000,
    "Julio Enciso": 20_000_000,
    "Kenan Yıldız": 75_000_000,
    "Christian Pulisic": 60_000_000,
    # Group E
    "Leandro Bacuna": 1_500_000,
    "Moisés Caicedo": 90_000_000,
    "Florian Wirtz": 140_000_000,
    "Amad Diallo": 45_000_000,
    # Group F
    "Takefusa Kubo": 60_000_000,
    "Frenkie de Jong": 70_000_000,
    "Alexander Isak": 120_000_000,
    "Hannibal Mejbri": 10_000_000,
    # Group G
    "Jérémy Doku": 60_000_000,
    "Mohamed Salah": 50_000_000,
    "Mehdi Taremi": 12_000_000,
    "Chris Wood": 5_000_000,
    # Group H
    "Ryan Mendes": 1_500_000,
    "Salem Al-Dawsari": 6_000_000,
    "Lamine Yamal": 200_000_000,
    "Pedri": 140_000_000,
    "Federico Valverde": 130_000_000,
    # Group I
    "Kylian Mbappé": 180_000_000,
    "Aymen Hussein": 1_500_000,
    "Erling Haaland": 180_000_000,
    "Martin Ødegaard": 90_000_000,
    "Nicolas Jackson": 65_000_000,
    # Group J
    "Amine Gouiri": 30_000_000,
    "Julián Álvarez": 90_000_000,
    "Lautaro Martínez": 90_000_000,
    "Konrad Laimer": 25_000_000,
    "Musa Al-Taamari": 9_000_000,
    # Group K
    "Luis Díaz": 80_000_000,
    "Yoane Wissa": 25_000_000,
    "Rafael Leão": 90_000_000,
    "Vitinha": 70_000_000,
    "Abbosbek Fayzullaev": 12_000_000,
    # Group L
    "Joško Gvardiol": 75_000_000,
    "Jude Bellingham": 180_000_000,
    "Bukayo Saka": 140_000_000,
    "Antoine Semenyo": 50_000_000,
    "José Fajardo": 1_500_000,
}


def main():
    squads_path = os.path.join(HERE, "cache", "squads.json")
    teams = json.load(open(squads_path, encoding="utf-8"))
    by_slug = {}
    for t in teams:
        for p in t["players"]:
            if p.get("name") and p.get("year_of_birth"):
                by_slug.setdefault(slug(p["name"]), p)

    out = {}
    unmatched = []
    for name, value in CURATED.items():
        p = by_slug.get(slug(name))
        if not p:
            unmatched.append(name)
            continue
        pid = f"{slug(p['name'])}-{p['year_of_birth']}"
        out[pid] = {"name": p["name"], "marketValueEUR": value}

    out = dict(sorted(out.items()))
    with open(os.path.join(HERE, "market_values.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"wrote market_values.json: {len(out)} players")
    if unmatched:
        print("UNMATCHED (fix the curated name):")
        for n in unmatched:
            print("  -", n)


if __name__ == "__main__":
    main()

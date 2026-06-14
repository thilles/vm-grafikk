#!/usr/bin/env python3
"""Scrape ekte markedsverdier fra Transfermarkt og skriv market_values.json
(kilden for wc:marketValueEUR i grafen).

Itererer per landslag via Transfermarkts VM-side filtrert på land_id, slik at
ALLE spillere i hver tropp fanges – ikke bare de med en nylig verdiendring:

  https://www.transfermarkt.com/world-cup/marktwertaenderungen/pokalwettbewerb/
  FIWC/plus//galerie/0?land_id=<id>

Høflig: beskrivende User-Agent, pause mellom kall, og hver landsside caches til
cache/ slik at reruns er offline. Verdiene matches mot de parsede troppene
(cache/squads.json) på navne-slug, så nøklene blir de kanoniske spiller-id-ene
(slug(navn)-fødselsår) som grafen bruker.
"""
import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup

from uris import slug

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
URL = ("https://www.transfermarkt.com/world-cup/marktwertaenderungen/"
       "pokalwettbewerb/FIWC/plus//galerie/0?pos=&detailpos=&land_id={lid}")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
PAUSE = 2.0

# Transfermarkts land_id for hver av de 48 VM-nasjonene (hentet fra land-velgeren).
LAND_ID = {
    "Czech Republic": "172", "Mexico": "110", "South Africa": "159", "South Korea": "87",
    "Bosnia and Herzegovina": "24", "Canada": "80", "Qatar": "137", "Switzerland": "148",
    "Brazil": "26", "Haiti": "62", "Morocco": "107", "Scotland": "190",
    "Australia": "12", "Paraguay": "132", "Turkey": "174", "United States": "184",
    "Curaçao": "260", "Ecuador": "44", "Germany": "40", "Ivory Coast": "38",
    "Japan": "77", "Netherlands": "122", "Sweden": "147", "Tunisia": "173",
    "Belgium": "19", "Egypt": "2", "Iran": "71", "New Zealand": "120",
    "Cape Verde": "32", "Saudi Arabia": "146", "Spain": "157", "Uruguay": "179",
    "France": "50", "Iraq": "70", "Norway": "125", "Senegal": "149",
    "Algeria": "4", "Argentina": "9", "Austria": "127", "Jordan": "78",
    "Colombia": "83", "DR Congo": "193", "Portugal": "136", "Uzbekistan": "180",
    "Croatia": "37", "England": "189", "Ghana": "54", "Panama": "130",
}


def _fetch(nation, lid):
    path = os.path.join(CACHE, f"tm_land_{lid}.html")
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    time.sleep(PAUSE)
    r = requests.get(URL.format(lid=lid),
                     headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=40)
    r.raise_for_status()
    open(path, "w", encoding="utf-8").write(r.text)
    return r.text


def _parse_eur(text):
    s = (text or "").replace("€", "").replace(",", "").strip().lower()
    m = re.search(r"([\d.]+)\s*([mk]?)", s)
    if not m:
        return None
    return int(float(m.group(1)) * {"m": 1_000_000, "k": 1_000}.get(m.group(2), 1))


def _parse_rows(html):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for r in soup.select("table.items tbody > tr"):
        a = r.select_one("td.hauptlink a")
        tds = r.find_all("td", recursive=False)
        if not a or not tds:
            continue
        name = a.get_text(strip=True)
        value = _parse_eur(tds[-1].get_text(strip=True))
        if name and value:
            out.append((name, value))
    return out


def _tkey(name):
    """Rekkefølge-uavhengig nøkkel (sorterte navne-ord) – fanger romaniserings-
    forskjeller som «Son Heung-min» (Wikipedia) vs «Heung-min Son» (TM)."""
    return "-".join(sorted(slug(name).split("-")))


def main():
    os.makedirs(CACHE, exist_ok=True)
    # Bygg TM-verdi per land (scoping unngår navnekollisjoner på tvers av lag).
    tm = {}  # nation -> {"exact": {slug: (name,value)}, "tok": {tkey: (name,value)}}
    for nation, lid in LAND_ID.items():
        rows = _parse_rows(_fetch(nation, lid))
        exact, tok = {}, {}
        for name, value in rows:
            s = slug(name)
            if s not in exact or value > exact[s][1]:
                exact[s] = (name, value)
            tok[_tkey(name)] = (name, value)
        tm[nation] = {"exact": exact, "tok": tok}
        print(f"  {nation:24} {len(rows)} spillere")

    teams = json.load(open(os.path.join(CACHE, "squads.json"), encoding="utf-8"))
    out, matched, unmatched = {}, 0, []
    for t in teams:
        d = tm.get(t["name"], {"exact": {}, "tok": {}})
        for p in t["players"]:
            if not p.get("name") or not p.get("year_of_birth"):
                continue
            hit = d["exact"].get(slug(p["name"])) or d["tok"].get(_tkey(p["name"]))
            if not hit:
                unmatched.append(f"{t['name']}: {p['name']}")
                continue
            pid = f"{slug(p['name'])}-{p['year_of_birth']}"
            out[pid] = {"name": p["name"], "marketValueEUR": hit[1], "source": "transfermarkt"}
            matched += 1

    out = dict(sorted(out.items()))
    with open(os.path.join(HERE, "market_values.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    total = sum(len(t["players"]) for t in teams)
    print(f"\nmarket_values.json: {matched}/{total} spillere med ekte verdi")
    print(f"uten match: {len(unmatched)}")
    for u in unmatched[:25]:
        print("  -", u)


if __name__ == "__main__":
    main()

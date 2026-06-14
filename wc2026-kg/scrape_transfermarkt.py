#!/usr/bin/env python3
"""Scrape ekte markedsverdier fra Transfermarkt sin VM-2026-oversikt og skriv
market_values.json (kilden for wc:marketValueEUR i grafen).

Side: https://www.transfermarkt.com/weltmeisterschaft/marktwertaenderungen/
      pokalwettbewerb/FIWC  (paginert, 25 spillere per side)

Høflig: beskrivende User-Agent, pause mellom kall, og hver side caches til
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
BASE = "https://www.transfermarkt.com/weltmeisterschaft/marktwertaenderungen/pokalwettbewerb/FIWC"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
PAUSE = 2.0


def _fetch_page(n):
    path = os.path.join(CACHE, f"tm_mwa_{n:02d}.html")
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    url = BASE if n == 1 else f"{BASE}/page/{n}"
    time.sleep(PAUSE)
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=40)
    r.raise_for_status()
    open(path, "w", encoding="utf-8").write(r.text)
    return r.text


def _parse_eur(text):
    s = (text or "").replace("€", "").replace(",", "").strip().lower()
    m = re.search(r"([\d.]+)\s*([mk]?)", s)
    if not m:
        return None
    return int(float(m.group(1)) * {"m": 1_000_000, "k": 1_000}.get(m.group(2), 1))


def _last_page(html):
    pages = {int(m.group(1)) for m in
             re.finditer(r"/marktwertaenderungen/pokalwettbewerb/FIWC/page/(\d+)", html)}
    return max(pages) if pages else 1


def _parse_rows(html):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for r in soup.select("table.items tbody > tr"):
        a = r.select_one("td.hauptlink a")
        tds = r.find_all("td", recursive=False)
        if not a or not tds:
            continue
        name = a.get_text(strip=True)
        pid = None
        m = re.search(r"/spieler/(\d+)", a.get("href", ""))
        if m:
            pid = m.group(1)
        value = _parse_eur(tds[-1].get_text(strip=True))
        if name and value:
            out.append((name, pid, value))
    return out


def main():
    os.makedirs(CACHE, exist_ok=True)
    first = _fetch_page(1)
    last = _last_page(first)
    print(f"sider: {last}")
    seen_ids, tm_by_slug = set(), {}
    total = 0
    for n in range(1, last + 1):
        html = first if n == 1 else _fetch_page(n)
        for name, pid, value in _parse_rows(html):
            if pid and pid in seen_ids:
                continue
            if pid:
                seen_ids.add(pid)
            total += 1
            # behold høyeste hvis samme slug dukker opp flere ganger
            s = slug(name)
            if s not in tm_by_slug or value > tm_by_slug[s][1]:
                tm_by_slug[s] = (name, value)
        print(f"  side {n}/{last} ferdig ({total} spillere så langt)")

    # match mot troppene
    teams = json.load(open(os.path.join(CACHE, "squads.json"), encoding="utf-8"))
    out, matched, unmatched = {}, 0, []
    for t in teams:
        for p in t["players"]:
            if not p.get("name") or not p.get("year_of_birth"):
                continue
            hit = tm_by_slug.get(slug(p["name"]))
            if not hit:
                unmatched.append(p["name"])
                continue
            pid = f"{slug(p['name'])}-{p['year_of_birth']}"
            out[pid] = {"name": p["name"], "marketValueEUR": hit[1], "source": "transfermarkt"}
            matched += 1

    out = dict(sorted(out.items()))
    with open(os.path.join(HERE, "market_values.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\nTransfermarkt-spillere lest: {len(tm_by_slug)}")
    print(f"market_values.json skrevet: {matched} spillere matchet mot troppene")
    print(f"uten verdi (ikke funnet på TM): {len(unmatched)}")
    if unmatched[:15]:
        print("  eksempler uten match:", unmatched[:15])


if __name__ == "__main__":
    main()

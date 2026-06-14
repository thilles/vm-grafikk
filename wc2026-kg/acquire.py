"""Data acquisition for the 2026 FIFA World Cup squads knowledge graph.

Primary source: the Wikipedia article "2026 FIFA World Cup squads" via the
MediaWiki API. All raw HTTP responses are cached to ./cache/ so reruns are
offline, polite and deterministic. Every network call is rate-limited and sends
a descriptive User-Agent.

Parsing strategy: walk the rendered article in document order, tracking the
current Group (h2) and nation (h3) heading; parse every table that carries the
squad-table header signature (No./Pos./Player/Caps/Goals/Club).
"""
import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup

ARTICLE = "2026 FIFA World Cup squads"
API = "https://en.wikipedia.org/w/api.php"
UA = "wc2026-kg/1.0 (educational research; +https://example.org/wc2026)"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
_LAST_CALL = [0.0]
_MIN_INTERVAL = 1.0  # seconds between live API calls (politeness)


def _get(params, cache_name, timeout=60):
    """GET against the MediaWiki API with on-disk JSON caching + rate limiting."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, cache_name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    wait = _MIN_INTERVAL - (time.time() - _LAST_CALL[0])
    if wait > 0:
        time.sleep(wait)
    r = requests.get(API, params=params, headers={"User-Agent": UA}, timeout=timeout)
    _LAST_CALL[0] = time.time()
    r.raise_for_status()
    data = r.json()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    return data


def fetch_article_html():
    data = _get(
        {"action": "parse", "page": ARTICLE, "format": "json",
         "prop": "text", "formatversion": "2"},
        "squads_parse.json",
    )
    return data["parse"]["text"]


_FLAG_RE = re.compile(r"Flag_of_(?:the_)?(.+?)\.svg", re.IGNORECASE)
_DOB_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_POS_RE = re.compile(r"\b(GK|DF|MF|FW)\b")


def _int(text):
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def _is_squad_header(table):
    first = table.find("tr")
    if not first:
        return False
    cells = [c.get_text(" ", strip=True) for c in first.find_all(["th", "td"])]
    joined = " ".join(cells).lower()
    return all(k in joined for k in ("player", "caps", "goals", "club")) and \
        ("no." in joined or "pos." in joined)


def _club_from_cell(cell):
    """Return (club_name, club_wiki_title, club_country) from a Club cell."""
    country = None
    flag = cell.find("img")
    if flag and flag.get("src"):
        m = _FLAG_RE.search(flag["src"])
        if m:
            country = m.group(1).replace("_", " ").strip()
    club_name, club_title = None, None
    for a in cell.find_all("a"):
        if a.find_parent("span", class_="flagicon"):
            continue  # skip the country/association flag link
        txt = a.get_text(strip=True)
        if not txt:
            continue
        club_name = txt
        href = a.get("href", "")
        if href.startswith("/wiki/"):
            club_title = href[len("/wiki/"):].split("#")[0]
        break
    if not club_name:  # unlinked club: take text after the flag
        club_name = cell.get_text(" ", strip=True) or None
    return club_name, club_title, country


def parse_squads(html, nations):
    """Parse the article HTML into a list of team dicts.

    `nations` is the lookups.NATIONS mapping (heading name -> (code, conf)).
    """
    soup = BeautifulSoup(html, "lxml")
    teams = {}
    current_group = None
    current_nation = None

    for el in soup.find_all(["h2", "h3", "table"]):
        if el.name == "h2":
            text = el.get_text(" ", strip=True)
            m = re.match(r"Group ([A-L])\b", text)
            current_group = m.group(1) if m else None
            current_nation = None  # leaving any nation (e.g. into Statistics)
            continue
        if el.name == "h3":
            text = el.get_text(" ", strip=True)
            current_nation = text if text in nations else None
            continue
        # table
        if not current_nation or not current_group:
            continue
        if not _is_squad_header(el):
            continue
        team = teams.setdefault(current_nation, {
            "name": current_nation,
            "group": current_group,
            "players": [],
        })
        for tr in el.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < 7:
                continue
            no, pos, player, dob, caps, goals, club = cells[:7]
            pm = _POS_RE.search(pos.get_text(" ", strip=True))
            # player name = first non-flag link text, else cell text
            name = None
            for a in player.find_all("a"):
                if a.find_parent("span", class_="flagicon"):
                    continue
                if a.get_text(strip=True):
                    name = a.get_text(strip=True)
                    break
            if not name:
                name = player.get_text(" ", strip=True)
            name = re.sub(r"\s*\((?:c|captain)\)\s*", "", name).strip()
            dm = _DOB_RE.search(dob.get_text(" ", strip=True))
            club_name, club_title, club_country = _club_from_cell(club)
            team["players"].append({
                "shirt": _int(no.get_text(strip=True)),
                "position": pm.group(1) if pm else None,
                "name": name,
                "dob": f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}" if dm else None,
                "year_of_birth": int(dm.group(1)) if dm else None,
                "caps": _int(caps.get_text(strip=True)),
                "goals": _int(goals.get_text(strip=True)),
                "club": club_name,
                "club_title": club_title,
                "club_country": club_country,
            })
    return list(teams.values())


WDQS = "https://query.wikidata.org/sparql"


def fetch_leagues_wikidata(club_titles):
    """Authoritative club -> (league, league_country) via Wikidata P118.

    Matches each club by its English Wikipedia sitelink (the URL-encoded href
    title used as-is). Batched, cached, best-effort: any failure leaves the
    affected clubs for the wikitext fallback. Resolves leagues that the infobox
    hides behind '{{football updater}}' templates (Premier League, La Liga, ...).
    """
    titles = sorted({t for t in club_titles if t})
    out = {}
    for i in range(0, len(titles), 80):
        batch = titles[i:i + 80]
        values = " ".join(f"<https://en.wikipedia.org/wiki/{t}>" for t in batch)
        query = f"""SELECT ?article ?leagueLabel ?countryLabel WHERE {{
  VALUES ?article {{ {values} }}
  ?article schema:about ?club ; schema:isPartOf <https://en.wikipedia.org/> .
  ?club wdt:P118 ?league .
  OPTIONAL {{ ?league wdt:P17 ?country. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}"""
        path = os.path.join(CACHE, f"wd_leagues_{i//80:02d}.json")
        try:
            if os.path.exists(path):
                data = json.load(open(path, encoding="utf-8"))
            else:
                wait = _MIN_INTERVAL - (time.time() - _LAST_CALL[0])
                if wait > 0:
                    time.sleep(wait)
                r = requests.post(WDQS, data={"query": query, "format": "json"},
                                  headers={"User-Agent": UA,
                                           "Accept": "application/sparql-results+json"},
                                  timeout=120)
                _LAST_CALL[0] = time.time()
                r.raise_for_status()
                data = r.json()
                json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 - graceful degradation
            print(f"  [wikidata] batch {i//80} failed, skipping: {exc}")
            continue
        for b in data.get("results", {}).get("bindings", []):
            title = b["article"]["value"].split("/wiki/")[-1]
            league = b.get("leagueLabel", {}).get("value")
            country = b.get("countryLabel", {}).get("value")
            if league and not league.startswith("Q"):  # skip unlabelled QIDs
                out.setdefault(title, (league, country))
    return out


def _rev_content(page):
    try:
        rev = page["revisions"][0]
    except (KeyError, IndexError):
        return None
    if "content" in rev:               # formatversion=2 flat content
        return rev["content"]
    try:                               # slot-based content
        return rev["slots"]["main"]["content"]
    except (KeyError, IndexError):
        return None


def fetch_club_leagues(club_titles):
    """Best-effort: map club wiki title -> league name via infobox wikitext.

    Batched (<=50 titles/request) against the API, following redirects; cached.
    Wiki titles from hrefs are URL-encoded, so they are unquoted before the
    request. Never raises — on any failure the affected clubs get no league.
    """
    from urllib.parse import unquote
    titles = sorted({t for t in club_titles if t})
    league_re = re.compile(r"\|\s*league\s*=\s*(.+)", re.IGNORECASE)
    link_re = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
    out = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        # encoded-title -> human title sent to the API
        decoded = {t: unquote(t).replace("_", " ") for t in batch}
        try:
            data = _get(
                {"action": "query", "prop": "revisions", "rvprop": "content",
                 "rvslot": "main", "format": "json", "formatversion": "2",
                 "redirects": "1",
                 "titles": "|".join(decoded.values())},
                f"clubs_batch_{i//50:02d}.json",
            )
        except Exception as exc:  # noqa: BLE001 - graceful degradation
            print(f"  [leagues] batch {i//50} failed, skipping: {exc}")
            continue
        query = data.get("query", {})
        pages = {p.get("title"): p for p in query.get("pages", [])}
        # chain: requested -> normalized -> redirect -> final page title
        norm = {n["from"]: n["to"] for n in query.get("normalized", [])}
        redir = {r["from"]: r["to"] for r in query.get("redirects", [])}
        for enc, human in decoded.items():
            title = norm.get(human, human)
            title = redir.get(title, title)
            page = pages.get(title)
            if not page:
                continue
            text = _rev_content(page)
            if not text:
                continue
            m = league_re.search(text)
            if not m:
                continue
            lm = link_re.search(m.group(1))
            if not lm:
                continue  # only trust proper [[wikilinks]]; skip templates/plain text
            league = lm.group(1).split("#")[0].strip()        # drop section anchors
            league = re.sub(r"^\d{4}[–-]\d{2,4}\s+", "", league)  # drop season-year prefix
            league = re.sub(r"\s+season$", "", league).strip()    # drop trailing 'season'
            if league:
                out[enc] = league
    return out

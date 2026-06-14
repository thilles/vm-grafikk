"""Nyhetsfeed fra NRKs Fotball-VM 2026-direkterapportering.

NRK eksponerer direktefeeden som en «compilation» (NRK_FEED_ID) via det åpne
serum-API-et. Compilationen gir en ordnet liste med post-referanser (id +
opprettet-tidspunkt); hver post hentes så enkeltvis for tittel, ingress og
publiseringstid. Ingen API-nøkkel kreves.

Postene caches pr id (de endres sjelden etter publisering), så bare nye/endrede
poster hentes ved hver oppdatering. Ved feil beholdes forrige vellykkede svar,
slik at en nede NRK-tjeneste ikke påvirker resten av appen.
"""

import html
import logging
import os
import re

import httpx

log = logging.getLogger("vm.news")

BASE = "https://www.nrk.no/serum/api/content/json"
# Compilation-id for direkterapporteringen på https://www.nrk.no/fotballvm2026/.
FEED_ID = os.environ.get("NRK_FEED_ID", "1.13470296")
FEED_URL = "https://www.nrk.no/fotballvm2026/"
MAX_ITEMS = int(os.environ.get("NRK_NEWS_MAX", "6"))

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# id -> {"created": ..., "item": {...}}. Beholdes mellom oppdateringer.
_cache = {}
# Forrige vellykkede feed (dict). Beholdes ved feil.
_last = None


def _strip_html(s):
    """Gjør NRKs ingress-HTML om til ren tekst for en kompakt feed."""
    if not s:
        return ""
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", s))).strip()


def _fetch_json(client, cid, limit=None):
    params = {"v": "2", "context": "items"}
    if limit:
        params["limit"] = str(limit)
    resp = client.get(f"{BASE}/{cid}", params=params)
    resp.raise_for_status()
    return resp.json()


def _build_item(client, cid):
    """Henter én post og plukker ut tittel, ingress og tidspunkt."""
    d = _fetch_json(client, cid)
    title = (d.get("title") or "").strip()
    if not title:
        return None
    return {
        "id": cid,
        "title": title,
        "summary": _strip_html(d.get("lead")),
        "published": d.get("published") or d.get("updated"),
    }


def build_news():
    """Returnerer {source, title, url, items}. Tom items-liste ved feil."""
    global _last
    try:
        with httpx.Client(
            timeout=20, headers={"User-Agent": "vm-grafikk/1.0"}
        ) as client:
            feed = _fetch_json(client, FEED_ID, limit=MAX_ITEMS)
            refs = [
                r
                for r in (feed.get("relations") or [])
                if r.get("context") == "items" and r.get("id")
            ][:MAX_ITEMS]

            items = []
            for r in refs:
                cid, created = r["id"], r.get("created")
                cached = _cache.get(cid)
                if cached and cached["created"] == created:
                    item = cached["item"]
                else:
                    item = _build_item(client, cid)
                    if item:
                        _cache[cid] = {"created": created, "item": item}
                if item:
                    items.append(item)

            # Hold cachen til bare postene som fortsatt ligger i feeden.
            for stale in set(_cache) - {r["id"] for r in refs}:
                _cache.pop(stale, None)

        _last = {
            "source": "NRK",
            "title": (feed.get("title") or "Fotball-VM 2026").strip(),
            "url": FEED_URL,
            "items": items,
        }
        log.info("Hentet %d nyheter fra NRK", len(items))
        return _last
    except httpx.HTTPError as e:
        log.warning("NRK-nyhetsfeed feilet: %s", e)
        return _last or {
            "source": "NRK",
            "title": "Fotball-VM 2026",
            "url": FEED_URL,
            "items": [],
        }

"""Kamphøydepunkt-videoer fra en YouTube-spilleliste (YouTube Data API v3).

Hver video i spillelista kobles til riktig kamp ved å parse lagnavnene ut av
videotittelen (f.eks. «Brazil v Morocco | Highlights | FIFA World Cup 26™») og
kjøre dem gjennom teams.canonical – samme mønster som api-sports-koblingen i
highlights.py. Koblingsnøkkelen er det sorterte kanoniske lagparet.

Spillelista hentes på nytt hver oppdatering (ett API-kall pr 50 videoer, godt
innenfor gratiskvoten på 10 000 enheter/døgn). Ved feil beholdes forrige svar.

Uten YOUTUBE_API_KEY er modulen en no-op (returnerer tom dict).
"""

import logging
import os
import re

import httpx

from .teams import canonical

log = logging.getLogger("vm.videos")

API = "https://www.googleapis.com/youtube/v3/playlistItems"
# Spilleliste-id fra delelenka (?list=…). Overstyrbar via env hvis den endres.
PLAYLIST_ID = os.environ.get("YOUTUBE_PLAYLIST_ID", "PLBRLtDhTHh5o")

# pair_key -> {"id": videoId, "title": tittel}. Beholdes mellom oppdateringer.
_videos = None

# Deler lagparet i to. Dekker «Lag A 4-1 Lag B» (resultat mellom lagene,
# som i FIFAs titler), «Lag A v/vs/x Lag B» og «Lag A - Lag B».
_SPLIT = re.compile(
    r"\s+\d+\s*[-–—]\s*\d+\s+"
    r"|\s+(?:vs?|x)\s+"
    r"|\s+[-–—]\s+",
    re.IGNORECASE,
)


def pair_key(m):
    """Sortert kanonisk lagpar – samme nøkkel som _parse_pair lager.

    m["home"]/m["away"] er allerede kanoniske (normalisert i football_api)."""
    return "|".join(sorted([m["home"], m["away"]]))


def _parse_pair(title):
    """Trekker «Lag A mot Lag B» ut av en videotittel -> pair_key, ellers None."""
    # Lagparet står som regel i ett av segmentene (delt på | eller :).
    for seg in re.split(r"[|:]", title):
        parts = _SPLIT.split(seg.strip())
        if len(parts) != 2:
            continue
        a, b = canonical(parts[0].strip()), canonical(parts[1].strip())
        if a and b and a != b:
            return "|".join(sorted([a, b]))
    return None


def _fetch_playlist(key):
    """{pair_key: {id, title}} for alle kamp-videoer i spillelista."""
    found, page = {}, None
    with httpx.Client(timeout=30) as client:
        for _ in range(40):  # opptil 40*50 = 2000 videoer
            params = {"part": "snippet", "maxResults": 50,
                      "playlistId": PLAYLIST_ID, "key": key}
            if page:
                params["pageToken"] = page
            resp = client.get(API, params=params)
            resp.raise_for_status()
            data = resp.json()
            for it in data.get("items") or []:
                sn = it.get("snippet") or {}
                vid = (sn.get("resourceId") or {}).get("videoId")
                pair = _parse_pair(sn.get("title") or "")
                if vid and pair and pair not in found:
                    found[pair] = {"id": vid, "title": sn.get("title")}
            page = data.get("nextPageToken")
            if not page:
                break
    return found


def build_videos():
    """Returnerer {pair_key: {id, title}}. No-op (tom dict) uten YOUTUBE_API_KEY."""
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        return {}

    global _videos
    try:
        _videos = _fetch_playlist(key)
        log.info("Fant %d kampvideoer i YouTube-spillelista", len(_videos))
    except httpx.HTTPError as e:
        log.warning("YouTube-spilleliste feilet: %s", e)
        if _videos is None:
            return {}
    return _videos or {}


def view(v):
    """Beriker en cachet video for frontend (embed bygges av video-id der)."""
    if not v:
        return None
    return {"id": v["id"], "title": v.get("title", "")}

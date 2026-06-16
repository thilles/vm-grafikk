"""Resolver et NRK-klipp-uuid til en spillbar HLS-strøm via NRKs psapi.

NIFS-hendelsene gir en klipp-uuid pr mål. NRKs psapi gir manifestet:
  GET https://psapi.nrk.no/playback/manifest/clip/<uuid>
-> playable.assets[].url (ukryptert HLS .m3u8). Manifestet sier også om klippet
er geoblokkert (Norge) og om ekstern innbygging er tillatt. Nøkkelfritt.
"""

import logging
import re

import httpx

log = logging.getLogger("vm.nrk_video")

PSAPI = "https://psapi.nrk.no/playback/manifest/clip/{uuid}"
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{20,40}$")
_HEADERS = {"Accept": "application/json", "User-Agent": "vm-grafikk/1.0"}


def resolve_clip(uuid):
    """Returnerer {m3u8, playable, geoBlocked} eller None ved feil/ugyldig uuid."""
    if not uuid or not _UUID_RE.match(uuid):
        return None
    try:
        resp = httpx.get(PSAPI.format(uuid=uuid), headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        d = resp.json()
    except httpx.HTTPError as e:
        log.warning("psapi-oppslag feilet for %s: %s", uuid, e)
        return None

    playable = d.get("playability") == "playable"
    avail = d.get("availability") or {}
    m3u8 = None
    for a in (d.get("playable") or {}).get("assets") or []:
        if a.get("format") == "HLS" and a.get("url"):
            m3u8 = a["url"]
            break
    return {
        "m3u8": m3u8,
        "playable": bool(playable and m3u8),
        "geoBlocked": bool(avail.get("isGeoBlocked")),
    }

"""Optional Transfermarkt enrichment: market value, height, preferred foot.

Transfermarkt is Cloudflare-protected, so this prefers a locally hosted
felipeall/transfermarkt-api (Docker). Point TRANSFERMARKT_API_URL at it
(default http://localhost:8010). EVERYTHING here is best-effort: any failure
(no server, timeout, unexpected payload) is swallowed per-player so the build
never breaks. If the server is unreachable at all, enrichment is skipped wholesale
and the graph is emitted without market-value/height/foot triples.
"""
import json
import os
import re
import time

import requests

from acquire import CACHE, UA

HERE = os.path.dirname(os.path.abspath(__file__))
API_URL = os.environ.get("TRANSFERMARKT_API_URL", "http://localhost:8010").rstrip("/")
ENABLED = os.environ.get("ENABLE_TRANSFERMARKT", "1") != "0"
_MV_RE = re.compile(r"([\d.]+)\s*([mk]?)", re.IGNORECASE)


def _cache_path(name):
    return os.path.join(CACHE, "tm_" + name + ".json")


def load_static_market_values(path=None):
    """Load the curated, offline market-value snapshot (market_values.json).

    Returns {player_id -> marketValueEUR}, where player_id is the canonical
    slug(name)-yearOfBirth used in the URIs. Empty dict if the file is absent.
    Never raises.
    """
    path = path or os.path.join(HERE, "market_values.json")
    if not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for pid, rec in data.items():
        val = rec.get("marketValueEUR") if isinstance(rec, dict) else rec
        if val:
            out[pid] = int(val)
    return out


def available():
    """Quick liveness probe; False -> skip enrichment entirely."""
    if not ENABLED:
        return False
    try:
        r = requests.get(API_URL + "/", timeout=4, headers={"User-Agent": UA})
        return r.status_code < 500
    except Exception:  # noqa: BLE001
        return False


def _parse_market_value(val):
    """'€25.00m' / '750k' / 25000000 -> EUR as int, or None."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).replace("€", "").replace(",", "").strip()
    m = _MV_RE.search(s)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2).lower()
    mult = {"m": 1_000_000, "k": 1_000}.get(unit, 1)
    return int(num * mult)


def enrich_player(name, club=None):
    """Return {marketValueEUR, heightCm, preferredFoot} (subset) or {}.

    Cached per player slug. Never raises.
    """
    from uris import slug
    key = slug(f"{name}-{club or ''}")
    path = _cache_path(key)
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    result = {}
    try:
        s = requests.get(f"{API_URL}/players/search/{requests.utils.quote(name)}",
                         timeout=8, headers={"User-Agent": UA})
        s.raise_for_status()
        hits = s.json().get("results") or []
        if not hits:
            raise ValueError("no match")
        pid = hits[0]["id"]
        time.sleep(0.3)
        p = requests.get(f"{API_URL}/players/{pid}/profile",
                         timeout=8, headers={"User-Agent": UA})
        p.raise_for_status()
        prof = p.json()
        mv = _parse_market_value(prof.get("marketValue"))
        if mv:
            result["marketValueEUR"] = mv
        h = prof.get("height")
        if h:
            hm = re.search(r"(\d)[.,](\d{2})", str(h))
            if hm:
                result["heightCm"] = int(hm.group(1)) * 100 + int(hm.group(2))
            elif str(h).isdigit():
                result["heightCm"] = int(h)
        foot = prof.get("foot")
        if foot:
            result["preferredFoot"] = str(foot).lower()
    except Exception as exc:  # noqa: BLE001 - graceful per-player skip
        result = {}
    try:
        json.dump(result, open(path, "w", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return result

"""Deterministic, idempotent, UTF-8-safe URI construction.

Slugify is applied ONLY to the local part of a URI (lowercase, diacritics
stripped). Full names *with* diacritics are kept in the RDF literals by the
graph builder, never here.
"""
from slugify import slugify as _slugify

WC = "http://example.org/wc2026/ontology#"
WCR = "http://example.org/wc2026/resource/"


def slug(text: str) -> str:
    """Lowercase, diacritic-free, hyphenated slug safe for a URI local part."""
    return _slugify(text or "", lowercase=True)


def player_uri(name: str, year_of_birth) -> str:
    return f"{WCR}player/{slug(name)}-{year_of_birth}"


def team_uri(country: str) -> str:
    return f"{WCR}team/{slug(country)}"


def club_uri(name: str) -> str:
    return f"{WCR}club/{slug(name)}"


def league_uri(name: str) -> str:
    return f"{WCR}league/{slug(name)}"


def country_uri(code_or_name: str) -> str:
    return f"{WCR}country/{slug(code_or_name)}"


def group_uri(letter: str) -> str:
    return f"{WCR}group/{letter.upper()}"


def confederation_uri(name: str) -> str:
    return f"{WCR}confederation/{name.upper()}"


def position_uri(code: str) -> str:
    return f"{WCR}position/{code.upper()}"

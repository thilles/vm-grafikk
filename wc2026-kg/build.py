#!/usr/bin/env python3
"""End-to-end build of the 2026 FIFA World Cup squads knowledge graph.

Steps: acquire (cached) -> parse -> optional club-league + Transfermarkt
enrichment -> emit ontology.ttl / data.ttl / wc2026.ttl -> validate by
re-loading with rdflib -> run the four demo SPARQL queries.

Idempotent: reruns read from ./cache and produce byte-identical URIs/triples.
"""
import json
import os
import sys

from rdflib import Graph

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import acquire          # noqa: E402
import lookups          # noqa: E402
import enrich           # noqa: E402
from ontology import build_ontology, WC, WCR  # noqa: E402
from graph import build_data  # noqa: E402


def acquire_data():
    print("== STEP 1: acquire & parse ==")
    html = acquire.fetch_article_html()
    teams = acquire.parse_squads(html, lookups.NATIONS)
    # verification
    n_teams = len(teams)
    n_players = sum(len(t["players"]) for t in teams)
    groups = sorted({t["group"] for t in teams})
    oversized = [(t["name"], len(t["players"])) for t in teams if len(t["players"]) > 26]
    assert n_teams == 48, f"expected 48 teams, got {n_teams}"
    assert len(groups) == 12, f"expected 12 groups, got {len(groups)}"
    assert not oversized, f"squads over 26: {oversized}"
    print(f"  {n_teams} teams, {len(groups)} groups, {n_players} players (all squads <=26)")
    # cache parsed squads for inspection / offline reuse
    with open(os.path.join(acquire.CACHE, "squads.json"), "w", encoding="utf-8") as fh:
        json.dump(teams, fh, ensure_ascii=False, indent=2)

    titles = [p["club_title"] for t in teams for p in t["players"] if p.get("club_title")]
    print("  fetching club leagues from Wikidata (best-effort)...")
    wd = acquire.fetch_leagues_wikidata(titles)          # title -> (league, country)
    print(f"    Wikidata resolved {len(wd)} clubs")
    print("  filling gaps from infobox wikitext (best-effort)...")
    wt = acquire.fetch_club_leagues(titles)              # title -> league
    # merge: Wikidata wins; wikitext fills the rest (country falls back later)
    club_leagues = dict(wd)
    for title, league in wt.items():
        club_leagues.setdefault(title, (league, None))
    print(f"  resolved leagues for {len(club_leagues)} distinct clubs total")
    return teams, club_leagues


def emit(teams, club_leagues, enrich_fn):
    print("== STEP 2-4: build & emit Turtle ==")
    tbox = build_ontology()
    abox = build_data(teams, club_leagues, enrich_fn)

    tbox.serialize(os.path.join(HERE, "ontology.ttl"), format="turtle")
    abox.serialize(os.path.join(HERE, "data.ttl"), format="turtle")

    combined = Graph()
    combined += tbox
    combined += abox
    combined.serialize(os.path.join(HERE, "wc2026.ttl"), format="turtle")
    print(f"  ontology.ttl: {len(tbox)} triples")
    print(f"  data.ttl:     {len(abox)} triples")
    print(f"  wc2026.ttl:   {len(combined)} triples")
    return combined


def validate():
    print("== STEP 5: validate (re-parse with rdflib) ==")
    g = Graph()
    g.parse(os.path.join(HERE, "wc2026.ttl"), format="turtle")
    print(f"  parsed OK: {len(g)} triples")
    q = """
    PREFIX wc: <http://example.org/wc2026/ontology#>
    SELECT ?cls (COUNT(?s) AS ?n) WHERE {
      VALUES ?cls { wc:Tournament wc:NationalTeam wc:Player wc:Club wc:League
                    wc:Group wc:Confederation wc:Country wc:Position }
      ?s a ?cls .
    } GROUP BY ?cls ORDER BY DESC(?n)
    """
    for row in g.query(q):
        print(f"    {str(row.cls).split('#')[-1]:14} {int(row.n)}")
    return g


def demo_queries(g, enriched):
    print("\n== STEP 5: demo SPARQL queries ==")
    P = "PREFIX wc: <http://example.org/wc2026/ontology#>\n" \
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"

    print("\n-- 1. Player count per group --")
    q1 = P + """
    SELECT ?group (COUNT(?player) AS ?players) WHERE {
      ?team wc:inGroup ?g ; wc:calledUp ?player .
      ?g rdfs:label ?group .
    } GROUP BY ?group ORDER BY ?group """
    for r in g.query(q1):
        print(f"   {str(r.group):9} {int(r.players)}")

    print("\n-- 2. Top 10 clubs by players sent --")
    q2 = P + """
    SELECT ?club (COUNT(?player) AS ?n) WHERE {
      ?player wc:playsAtClub ?c . ?c rdfs:label ?club .
    } GROUP BY ?club ORDER BY DESC(?n) ?club LIMIT 10 """
    for r in g.query(q2):
        print(f"   {int(r.n):3}  {r.club}")

    print("\n-- 3. All forwards (FW) for Brazil, with shirt number and club --")
    q3 = P + """
    SELECT ?shirt ?name ?club WHERE {
      ?team rdfs:label "Brazil"@en ; wc:calledUp ?p .
      ?p wc:hasPosition <http://example.org/wc2026/resource/position/FW> ;
         foaf:name ?name .
      OPTIONAL { ?p wc:shirtNumber ?shirt }
      OPTIONAL { ?p wc:playsAtClub ?cl . ?cl rdfs:label ?club }
    } ORDER BY ?shirt """
    q3 = q3.replace("PREFIX rdfs:", "PREFIX foaf: <http://xmlns.com/foaf/0.1/>\nPREFIX rdfs:")
    rows = list(g.query(q3))
    for r in rows:
        print(f"   #{str(r.shirt or '?'):3} {str(r.name):24} {r.club or ''}")
    if not rows:
        print("   (none)")

    print("\n-- 4. Most valuable player per team --")
    if not enriched:
        print("   (skipped: Transfermarkt enrichment did not run)")
        return
    q4 = P + """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    SELECT ?team ?name ?value WHERE {
      {
        SELECT ?t (MAX(?v) AS ?value) WHERE {
          ?t wc:calledUp ?pp . ?pp wc:marketValueEUR ?v .
        } GROUP BY ?t
      }
      ?t rdfs:label ?team ; wc:calledUp ?p .
      ?p wc:marketValueEUR ?value ; foaf:name ?name .
    } ORDER BY DESC(?value) """
    for r in g.query(q4):
        print(f"   {str(r.team):16} {str(r.name):22} €{int(float(r.value)):,}")


def make_enrich_fn():
    """Build the enrichment callback, or (None, False) if no source is available.

    Sources, merged (live overrides static for overlapping fields):
      - static market_values.json (offline snapshot)
      - live Transfermarkt API (market value + height + preferred foot)
    """
    from uris import slug
    static_values = enrich.load_static_market_values()
    live = enrich.available()
    if static_values:
        print(f"  static market values loaded: {len(static_values)} players")
    if live:
        print("  Transfermarkt API reachable -> live enrichment ON")
    if not static_values and not live:
        print("  No enrichment source -> SKIPPED (graceful)")
        return None, False

    def enrich_fn(pl):
        out = {}
        pid = f"{slug(pl['name'])}-{pl.get('year_of_birth')}"
        if pid in static_values:
            out["marketValueEUR"] = static_values[pid]
        if live:
            for k, v in (enrich.enrich_player(pl["name"], pl.get("club")) or {}).items():
                if v:
                    out[k] = v
        return out

    return enrich_fn, True


def main():
    teams, club_leagues = acquire_data()
    enrich_fn, enriched = make_enrich_fn()
    g = emit(teams, club_leagues, enrich_fn)
    g = validate()
    demo_queries(g, enriched)
    print("\nDone. Artifacts: ontology.ttl, data.ttl, wc2026.ttl")


if __name__ == "__main__":
    main()

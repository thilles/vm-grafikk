"""The ABox: turn parsed squad data into RDF using the wc: ontology.

De-duplicates shared clubs, leagues and countries so each distinct entity is a
single node. URIs are built by uris.py (deterministic & idempotent); literals
keep full diacritics.
"""
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD, FOAF

import lookups
import uris
from ontology import WC, WCR, SCHEMA, bind

TOURNAMENT = WCR["tournament/fifa-world-cup-2026"]


def _U(s):
    return URIRef(s)


def build_data(teams, club_leagues=None, enrich_fn=None):
    """Build the ABox graph.

    teams: list of {name, group, players:[...]}
    club_leagues: optional {club_wiki_title -> league name}
    enrich_fn: optional callable(name, club) -> {marketValueEUR, heightCm, preferredFoot}
    """
    club_leagues = club_leagues or {}
    g = Graph()
    bind(g)

    # --- Tournament ---
    g.add((TOURNAMENT, RDF.type, WC.Tournament))
    g.add((TOURNAMENT, RDFS.label, Literal("2026 FIFA World Cup", lang="en")))
    g.add((TOURNAMENT, FOAF.name, Literal("2026 FIFA World Cup")))

    # --- Controlled vocabularies: positions, confederations, groups ---
    for code, label in lookups.POSITIONS.items():
        p = _U(uris.position_uri(code))
        g.add((p, RDF.type, WC.Position))
        g.add((p, RDFS.label, Literal(f"{label} ({code})", lang="en")))
        g.add((p, SCHEMA.identifier, Literal(code)))

    for code, label in lookups.CONFEDERATIONS.items():
        c = _U(uris.confederation_uri(code))
        g.add((c, RDF.type, WC.Confederation))
        g.add((c, RDFS.label, Literal(code, lang="en")))
        g.add((c, SCHEMA.name, Literal(label, lang="en")))

    groups_seen = set()

    # de-dup registries: key -> URI (so we only emit each node once)
    countries = {}     # country display name -> URIRef
    clubs = {}         # club name -> URIRef
    leagues = {}       # league name -> URIRef

    def country_node(name, code=None):
        if not name:
            return None
        if name in countries:
            return countries[name]
        uri = _U(uris.country_uri(code or name))
        g.add((uri, RDF.type, WC.Country))
        g.add((uri, RDFS.label, Literal(name, lang="en")))
        if code:
            g.add((uri, SCHEMA.identifier, Literal(code)))
        countries[name] = uri
        return uri

    def league_node(name, country_name=None):
        if not name:
            return None
        if name in leagues:
            uri = leagues[name]
        else:
            uri = _U(uris.league_uri(name))
            g.add((uri, RDF.type, WC.League))
            g.add((uri, RDFS.label, Literal(name, lang="en")))
            leagues[name] = uri
        if country_name:
            cn = country_node(country_name)
            if cn:
                g.add((uri, WC.leagueInCountry, cn))
        return uri

    def club_node(name, country_name=None, league_name=None, league_country=None):
        if not name:
            return None
        if name in clubs:
            uri = clubs[name]
        else:
            uri = _U(uris.club_uri(name))
            g.add((uri, RDF.type, WC.Club))
            g.add((uri, RDFS.label, Literal(name, lang="en")))
            g.add((uri, FOAF.name, Literal(name)))
            clubs[name] = uri
        if country_name:
            cn = country_node(country_name)
            if cn:
                g.add((uri, WC.clubInCountry, cn))
        if league_name:
            ln = league_node(league_name, league_country or country_name)
            if ln:
                g.add((uri, WC.clubInLeague, ln))
        return uri

    # Pre-create the 48 nation countries with their FIFA codes so their URIs use
    # the code (country/nor), not a name slug, regardless of whether a club based
    # in that country is encountered first. Keeps the URI scheme deterministic.
    for team in teams:
        country_node(team["name"], lookups.fifa_code(team["name"]))

    for team in teams:
        nation = team["name"]
        code = lookups.fifa_code(nation)
        conf = lookups.confederation(nation)
        turi = _U(uris.team_uri(nation))
        g.add((turi, RDF.type, WC.NationalTeam))
        g.add((turi, RDFS.label, Literal(nation, lang="en")))
        if code:
            g.add((turi, WC.fifaCode, Literal(code)))
        g.add((turi, WC.squadSize, Literal(len(team["players"]), datatype=XSD.integer)))
        g.add((TOURNAMENT, WC.hasParticipant, turi))

        # group
        letter = team["group"]
        guri = _U(uris.group_uri(letter))
        if letter not in groups_seen:
            g.add((guri, RDF.type, WC.Group))
            g.add((guri, RDFS.label, Literal(f"Group {letter}", lang="en")))
            groups_seen.add(letter)
        g.add((turi, WC.inGroup, guri))

        # confederation
        if conf:
            g.add((turi, WC.affiliatedTo, _U(uris.confederation_uri(conf))))

        # country represented (= the nation itself as a Country node)
        nation_country = country_node(nation, code)
        if nation_country:
            g.add((turi, WC.representsCountry, nation_country))

        team_total_value = 0
        have_value = False

        for pl in team["players"]:
            if not pl.get("name") or not pl.get("year_of_birth"):
                continue
            puri = _U(uris.player_uri(pl["name"], pl["year_of_birth"]))
            g.add((puri, RDF.type, WC.Player))
            g.add((puri, FOAF.name, Literal(pl["name"])))          # full diacritics
            g.add((puri, RDFS.label, Literal(pl["name"], lang="en")))
            if pl.get("shirt") is not None:
                g.add((puri, WC.shirtNumber, Literal(pl["shirt"], datatype=XSD.integer)))
            if pl.get("dob"):
                g.add((puri, WC.dateOfBirth, Literal(pl["dob"], datatype=XSD.date)))
            if pl.get("caps") is not None:
                g.add((puri, WC.caps, Literal(pl["caps"], datatype=XSD.integer)))
            if pl.get("goals") is not None:
                g.add((puri, WC.goalsForCountry, Literal(pl["goals"], datatype=XSD.integer)))

            # squad membership (+ inverse)
            g.add((turi, WC.calledUp, puri))
            g.add((puri, WC.playsForNationalTeam, turi))

            # nationality = represented country
            if nation_country:
                g.add((puri, WC.hasNationality, nation_country))

            # position
            if pl.get("position"):
                g.add((puri, WC.hasPosition, _U(uris.position_uri(pl["position"]))))

            # club (+ country + league)
            if pl.get("club"):
                entry = club_leagues.get(pl.get("club_title"))   # (league, country) or None
                league_name, league_country = entry if entry else (None, None)
                curi = club_node(pl["club"], pl.get("club_country"),
                                 league_name, league_country)
                if curi:
                    g.add((puri, WC.playsAtClub, curi))

            # optional enrichment
            if enrich_fn:
                extra = enrich_fn(pl) or {}
                if extra.get("marketValueEUR"):
                    g.add((puri, WC.marketValueEUR,
                           Literal(extra["marketValueEUR"], datatype=XSD.decimal)))
                    team_total_value += extra["marketValueEUR"]
                    have_value = True
                if extra.get("heightCm"):
                    g.add((puri, WC.heightCm,
                           Literal(extra["heightCm"], datatype=XSD.integer)))
                if extra.get("preferredFoot"):
                    g.add((puri, WC.preferredFoot, Literal(extra["preferredFoot"])))

        if have_value:
            g.add((turi, WC.totalMarketValueEUR,
                   Literal(team_total_value, datatype=XSD.decimal)))

    return g

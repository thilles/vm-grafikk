"""The TBox: a custom but standards-aligned OWL ontology for WC-2026 squads.

Reuses foaf (Person/name) and schema where natural; everything domain-specific
lives in the wc: namespace. Returns an rdflib.Graph that build.py serialises to
ontology.ttl.
"""
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD, FOAF

WC = Namespace("http://example.org/wc2026/ontology#")
WCR = Namespace("http://example.org/wc2026/resource/")
SCHEMA = Namespace("https://schema.org/")


def bind(g):
    g.bind("wc", WC)
    g.bind("wcr", WCR)
    g.bind("owl", OWL)
    g.bind("rdf", RDF)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)
    g.bind("foaf", FOAF)
    g.bind("schema", SCHEMA)


CLASSES = {
    "Tournament": "Tournament",
    "NationalTeam": "National team",
    "Player": "Player",
    "Club": "Club",
    "League": "League",
    "Group": "Group",
    "Confederation": "Confederation",
    "Country": "Country",
    "Position": "Playing position",
}

# name -> (domain, range, inverse-name-or-None, comment)
OBJECT_PROPS = {
    "hasParticipant": ("Tournament", "NationalTeam", None,
                       "Links a tournament to a participating national team."),
    "inGroup": ("NationalTeam", "Group", None,
                "The group a national team is drawn into."),
    "affiliatedTo": ("NationalTeam", "Confederation", None,
                     "The confederation a national team is affiliated to."),
    "representsCountry": ("NationalTeam", "Country", None,
                          "The country a national team represents."),
    "calledUp": ("NationalTeam", "Player", "playsForNationalTeam",
                 "A player called up to this national team's squad."),
    "playsForNationalTeam": ("Player", "NationalTeam", "calledUp",
                             "The national team a player was called up to."),
    "playsAtClub": ("Player", "Club", None, "The club a player plays at."),
    "hasPosition": ("Player", "Position", None, "The player's playing position."),
    "hasNationality": ("Player", "Country", None, "The player's nationality."),
    "clubInLeague": ("Club", "League", None, "The league a club competes in."),
    "clubInCountry": ("Club", "Country", None, "The country a club is based in."),
    "leagueInCountry": ("League", "Country", None, "The country a league is run in."),
}

# name -> (domain, range-xsd, comment)
DATA_PROPS = {
    "shirtNumber": ("Player", XSD.integer, "Squad shirt number."),
    "dateOfBirth": ("Player", XSD.date, "Player date of birth."),
    "caps": ("Player", XSD.integer, "International caps for the national team."),
    "goalsForCountry": ("Player", XSD.integer, "International goals for the national team."),
    "marketValueEUR": ("Player", XSD.decimal, "Estimated market value in EUR (optional)."),
    "heightCm": ("Player", XSD.integer, "Height in centimetres (optional)."),
    "preferredFoot": ("Player", XSD.string, "Preferred foot (optional)."),
    "fifaCode": ("NationalTeam", XSD.string, "Three-letter FIFA country code."),
    "squadSize": ("NationalTeam", XSD.integer, "Number of players in the squad."),
    "totalMarketValueEUR": ("NationalTeam", XSD.decimal, "Sum of squad market values in EUR (optional)."),
}


def build_ontology():
    g = Graph()
    bind(g)

    onto = URIRef("http://example.org/wc2026/ontology")
    g.add((onto, RDF.type, OWL.Ontology))
    g.add((onto, RDFS.label, Literal("2026 FIFA World Cup squads ontology", lang="en")))
    g.add((onto, RDFS.comment, Literal(
        "A custom, standards-aligned ontology describing the squads of the 2026 "
        "FIFA World Cup: tournaments, national teams, players, clubs, leagues, "
        "groups, confederations, countries and playing positions.", lang="en")))

    for name, label in CLASSES.items():
        c = WC[name]
        g.add((c, RDF.type, OWL.Class))
        g.add((c, RDFS.label, Literal(label, lang="en")))
    # Player is a kind of foaf:Person
    g.add((WC.Player, RDFS.subClassOf, FOAF.Person))

    for name, (dom, rng, inv, comment) in OBJECT_PROPS.items():
        p = WC[name]
        g.add((p, RDF.type, OWL.ObjectProperty))
        g.add((p, RDFS.label, Literal(name, lang="en")))
        g.add((p, RDFS.comment, Literal(comment, lang="en")))
        g.add((p, RDFS.domain, WC[dom]))
        g.add((p, RDFS.range, WC[rng]))
        if inv:
            g.add((p, OWL.inverseOf, WC[inv]))

    for name, (dom, rng, comment) in DATA_PROPS.items():
        p = WC[name]
        g.add((p, RDF.type, OWL.DatatypeProperty))
        g.add((p, RDFS.label, Literal(name, lang="en")))
        g.add((p, RDFS.comment, Literal(comment, lang="en")))
        g.add((p, RDFS.domain, WC[dom]))
        g.add((p, RDFS.range, rng))

    return g

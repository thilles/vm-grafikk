"""Kunnskapsgraf-modul: laster VM-2026-troppenes RDF-graf (wc2026-kg) og kjører
read-only SPARQL-spørringer for «Utforsk grafen»-siden.

Grafen lastes én gang ved første bruk og holdes i minnet (~18k triples). Bare
lese-spørringer er mulige: rdflib sin Graph.query() utfører kun
SELECT/ASK/CONSTRUCT/DESCRIBE – SPARQL UPDATE (INSERT/DELETE/LOAD/…) går via en
egen update()-metode som aldri kalles her, så grafen kan ikke endres utenfra.
I tillegg er antall rader og spørringslengde begrenset.
"""
import os
import threading

# wc2026-kg/wc2026.ttl ligger ved siden av app/ i repoet og kopieres til
# /srv/wc2026-kg/ i Docker-imaget (se Dockerfile).
KG_TTL = os.environ.get(
    "KG_TTL",
    os.path.join(os.path.dirname(__file__), "..", "wc2026-kg", "wc2026.ttl"),
)

MAX_QUERY_CHARS = 8000
DEFAULT_LIMIT = 1000
MAX_LIMIT = 5000

WC = "http://example.org/wc2026/ontology#"

_graph = None  # lazy-lastet rdflib.Graph
# pyparsing (rdflib sin SPARQL-parser) er IKKE trådsikker ved første parsing –
# arity-deteksjonen deler mutbar tilstand. FastAPI kjører sync-endepunktene i en
# trådpool, så samtidige spørringer må serialiseres. Denne låsen vokter både
# innlasting og all g.query()-bruk.
_lock = threading.RLock()


def versions():
    """Faktiske kjøretids-versjoner – nyttig for å feilsøke parser-feil."""
    out = {}
    try:
        import rdflib
        out["rdflib"] = rdflib.__version__
    except Exception:  # noqa: BLE001
        out["rdflib"] = "ukjent"
    try:
        import pyparsing
        out["pyparsing"] = pyparsing.__version__
    except Exception:  # noqa: BLE001
        out["pyparsing"] = "ukjent"
    return out


_WARMUP = (
    "ASK { ?s ?p ?o }",
    "SELECT ?s (COUNT(?o) AS ?n) WHERE { ?s ?p ?o } GROUP BY ?s LIMIT 1",
    "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o } LIMIT 1",
)


def _load():
    global _graph
    if _graph is not None:
        return _graph
    with _lock:  # dobbeltsjekket låsing: parse grafen kun én gang
        if _graph is None:
            import logging
            from rdflib import Graph
            logging.getLogger("vm.kg").info("laster kunnskapsgraf (%s)", versions())
            g = Graph()
            g.parse(KG_TTL, format="turtle")
            # bind vanlige prefikser så spørringer slipper å deklarere dem
            g.bind("wc", WC)
            g.bind("wcr", "http://example.org/wc2026/resource/")
            g.bind("foaf", "http://xmlns.com/foaf/0.1/")
            g.bind("schema", "https://schema.org/")
            # varm opp SPARQL-parseren enkelt-trådet (løser pyparsing sin arity-
            # deteksjon én gang) før samtidige forespørsler treffer den
            for wq in _WARMUP:
                try:
                    list(g.query(wq))
                except Exception:  # noqa: BLE001
                    pass
            _graph = g
    return _graph


def available():
    return os.path.exists(KG_TTL)


def info():
    """Metadata til UI: triple-antall og instanser per klasse.

    Robust: versjoner og triple-antall returneres alltid, også om SPARQL-
    parseren skulle feile (da kommer i stedet et `query_error`-felt) – slik at
    /api/kg/info kan brukes til å se hvilken rdflib/pyparsing som faktisk kjører.
    """
    g = _load()
    result = {
        "triples": len(g),
        "versions": versions(),
        "classes": {},
        "prefixes": {
            "wc": WC,
            "wcr": "http://example.org/wc2026/resource/",
            "foaf": "http://xmlns.com/foaf/0.1/",
            "schema": "https://schema.org/",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        },
    }
    q = (
        "PREFIX wc: <%s> "
        "SELECT ?cls (COUNT(?s) AS ?n) WHERE { "
        "  VALUES ?cls { wc:Tournament wc:NationalTeam wc:Player wc:Club "
        "    wc:League wc:Group wc:Confederation wc:Country wc:Position } "
        "  ?s a ?cls . } GROUP BY ?cls ORDER BY DESC(?n)" % WC
    )
    try:
        with _lock:
            for row in g.query(q):
                result["classes"][str(row[0]).split("#")[-1]] = int(row[1])
    except Exception as exc:  # noqa: BLE001 – ikke skjul versjonsinfoen
        result["query_error"] = str(exc)
    return result


def _term_to_json(term):
    from rdflib import URIRef, Literal, BNode
    if isinstance(term, URIRef):
        return {"type": "uri", "value": str(term)}
    if isinstance(term, BNode):
        return {"type": "bnode", "value": str(term)}
    if isinstance(term, Literal):
        out = {"type": "literal", "value": str(term)}
        if term.datatype is not None:
            out["datatype"] = str(term.datatype)
        if term.language:
            out["xml:lang"] = term.language
        return out
    return {"type": "literal", "value": str(term)}


def run_query(query, limit=DEFAULT_LIMIT):
    """Kjør en read-only SPARQL-spørring.

    Returnerer en dict {content_type, body, truncated}. Hever ValueError ved
    ugyldig/forbudt spørring (rutehåndtereren gjør det om til HTTP 400).
    """
    if not query or not query.strip():
        raise ValueError("Tom spørring.")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"Spørringen er for lang (maks {MAX_QUERY_CHARS} tegn).")
    try:
        limit = max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT

    import json
    import itertools
    g = _load()
    # Hele parse + evaluering under låsen (pyparsing-parsingen er ikke trådsikker).
    with _lock:
        try:
            result = g.query(query)  # kaster ved UPDATE/ugyldig SPARQL
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Ugyldig eller ikke-tillatt spørring: {exc}") from exc

        rtype = result.type  # 'SELECT' | 'ASK' | 'CONSTRUCT' | 'DESCRIBE'

        if rtype == "ASK":
            body = json.dumps({"head": {}, "boolean": bool(result.askAnswer)})
            return {"content_type": "application/sparql-results+json",
                    "body": body, "truncated": False}

        if rtype in ("CONSTRUCT", "DESCRIBE"):
            turtle = result.serialize(format="turtle")
            if isinstance(turtle, bytes):
                turtle = turtle.decode("utf-8")
            return {"content_type": "text/turtle; charset=utf-8",
                    "body": turtle, "truncated": False}

        # SELECT: bygg standard SPARQL Results JSON, kappet ved `limit`
        vars_ = [str(v) for v in (result.vars or [])]
        rows = list(itertools.islice(iter(result), limit + 1))
        truncated = len(rows) > limit
        rows = rows[:limit]
        bindings = []
        for row in rows:
            b = {}
            for v in (result.vars or []):
                val = row[v]
                if val is not None:
                    b[str(v)] = _term_to_json(val)
            bindings.append(b)
    body = json.dumps({"head": {"vars": vars_},
                       "results": {"bindings": bindings}})
    return {"content_type": "application/sparql-results+json",
            "body": body, "truncated": truncated}


def team_labels():
    """Sorterte landslagsnavn (engelske rdfs:label) til nedtrekksmenyen."""
    g = _load()
    q = ("PREFIX wc: <%s> "
         "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
         "SELECT ?l WHERE { ?t a wc:NationalTeam ; rdfs:label ?l } ORDER BY ?l" % WC)
    with _lock:
        return [str(r[0]) for r in g.query(q)]


_PREFIXES = """
    PREFIX wc: <http://example.org/wc2026/ontology#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
"""


def _pack(nodes, links):
    return {
        "nodes": list(nodes.values()),
        "links": [{"source": s, "target": t, "rel": rel}
                  for (s, t, rel) in sorted(links)],
    }


def subgraph(team_label="Norway"):
    """Nodegraf for ett landslag: lag → gruppe og lag → spillere.

    Hever ValueError ved ukjent lag (gjøres om til HTTP 404 i ruten).
    """
    from rdflib import Literal
    g = _load()
    q = _PREFIXES + """
    SELECT ?team ?teamLabel ?group ?groupLabel ?player ?playerName WHERE {
      ?team a wc:NationalTeam ; rdfs:label ?tname ; rdfs:label ?teamLabel .
      OPTIONAL { ?team wc:inGroup ?group . ?group rdfs:label ?groupLabel }
      OPTIONAL { ?team wc:calledUp ?player . ?player foaf:name ?playerName }
    }
    """
    with _lock:
        rows = list(g.query(q, initBindings={"tname": Literal(team_label, lang="en")}))
    nodes, links = {}, set()

    def add(uri, label, kind):
        if uri and uri not in nodes:
            nodes[uri] = {"id": uri, "label": label, "type": kind}

    for r in rows:
        team_uri = str(r.team)
        add(team_uri, str(r.teamLabel), "team")
        if r.group:
            add(str(r.group), str(r.groupLabel), "group")
            links.add((team_uri, str(r.group), "inGroup"))
        if r.player:
            pl = str(r.player)
            add(pl, str(r.playerName), "player")
            links.add((team_uri, pl, "calledUp"))

    if not nodes:
        raise ValueError(f"Ukjent landslag: {team_label}")
    return {"team": team_label, **_pack(nodes, links)}

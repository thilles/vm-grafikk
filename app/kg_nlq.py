"""Naturlig språk → SPARQL for «Utforsk grafen»-siden.

Bruker Claude (Haiku 4.5) til å oversette et fritekst-spørsmål på norsk til en
read-only SPARQL-spørring mot VM-2026-ontologien, og til å skrive et kort norsk
svar basert på resultatradene. Selve kjøringen av spørringen skjer i kg.py
(read-only, med rad-/lengdetak og lås) – dette modulet rører aldri grafen.

Krever ANTHROPIC_API_KEY. Mangler nøkkelen er funksjonen av (available() → False)
og resten av /graf virker som før, akkurat som highlights.py uten APISPORTS_KEY.
"""
import json
import logging
import os

log = logging.getLogger("vm.kg_nlq")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = os.environ.get("KG_NLQ_MODEL", "claude-haiku-4-5")
# Maks antall resultatrader som sendes til oppsummerings-kallet (token-kontroll).
SUMMARY_MAX_ROWS = 50

_client = None  # lazy anthropic.Anthropic()


def available():
    return bool(ANTHROPIC_API_KEY)


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# Vokabularet Claude trenger for å skrive korrekt SPARQL. Holdes kompakt; bygget
# fra ontologien (wc2026-kg/ontology.py) og faktiske trippel-former i wc2026.ttl.
ONTOLOGY_SPEC = """\
Du oversetter spørsmål om VM 2026-tropper til ÉN read-only SPARQL-spørring mot en \
RDF-graf. Svar med KUN selve SPARQL-spørringen – ingen forklaring, ingen \
markdown, ingen ```-kodeblokker.

Prefikser (alltid tilgjengelige – ta dem likevel med i spørringen):
  PREFIX wc:   <http://example.org/wc2026/ontology#>
  PREFIX wcr:  <http://example.org/wc2026/resource/>
  PREFIX foaf: <http://xmlns.com/foaf/0.1/>
  PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
  PREFIX schema: <https://schema.org/>
  PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

Klasser (?s a wc:Klasse): Tournament, NationalTeam, Player, Club, League, Group,
Confederation, Country, Position.

Objekt-egenskaper:
  NationalTeam wc:calledUp Player        (tropp; invers: Player wc:playsForNationalTeam NationalTeam)
  NationalTeam wc:inGroup Group
  NationalTeam wc:affiliatedTo Confederation
  NationalTeam wc:representsCountry Country
  Player wc:playsAtClub Club
  Player wc:hasPosition Position
  Player wc:hasNationality Country
  Club wc:clubInLeague League
  Club wc:clubInCountry Country
  League wc:leagueInCountry Country

Datatype-egenskaper:
  Player wc:shirtNumber (int), wc:dateOfBirth (xsd:date), wc:caps (int),
    wc:goalsForCountry (int), wc:marketValueEUR (decimal, euro), wc:heightCm (int),
    wc:preferredFoot ("left"/"right")
  NationalTeam wc:fifaCode (str), wc:squadSize (int), wc:totalMarketValueEUR (decimal)

Navn/etiketter:
  - Alle entiteter har rdfs:label "..."@en (engelsk). Bruk @en i match og i SELECT.
  - Spillere har i tillegg foaf:name (med diakritikk) – bruk den for spillernavn.
  - Landslag: rdfs:label "Norway"@en, "Denmark"@en, ...
  - Land (Country): rdfs:label "Denmark"@en, "Brazil"@en, ...
  - Grupper: rdfs:label "Group A"@en ... "Group L"@en (bokstaver A–L).
  - Posisjon: rdfs:label "Forward (FW)"@en, schema:identifier "FW" (GK/DF/MF/FW).
  - Klubb: rdfs:label "AGF"@en. Liga: rdfs:label "Premier League"@en.

Regler:
  - Kun SELECT (eller ASK ved ja/nei). Aldri INSERT/DELETE/LOAD.
  - Ta alltid med en fornuftig LIMIT (f.eks. 200), unntatt ved COUNT/aggregat.
  - SELECT lesbare verdier: spillernavn via foaf:name, lag/land/klubb via rdfs:label.
  - Tallintervaller med FILTER, f.eks. FILTER(?v >= 150000000 && ?v <= 200000000).
  - «verdi/markedsverdi» = wc:marketValueEUR i euro (150 millioner = 150000000).
  - «spiller i <land>» betyr klubb i landet: ?p wc:playsAtClub ?c . ?c wc:clubInCountry ?co . ?co rdfs:label "<Land>"@en .
  - «yngst» = størst wc:dateOfBirth; «eldst» = minst. «per lag» → GROUP BY laget.

Eksempler:
Spørsmål: Hvor mange spillere spiller i Danmark?
SPARQL:
PREFIX wc: <http://example.org/wc2026/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT (COUNT(DISTINCT ?p) AS ?antall) WHERE {
  ?p wc:playsAtClub ?c . ?c wc:clubInCountry ?co . ?co rdfs:label "Denmark"@en .
}

Spørsmål: Vis spillere med verdi mellom 150 og 200 millioner euro
SPARQL:
PREFIX wc: <http://example.org/wc2026/ontology#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
SELECT ?navn ?verdi WHERE {
  ?p a wc:Player ; foaf:name ?navn ; wc:marketValueEUR ?verdi .
  FILTER(?verdi >= 150000000 && ?verdi <= 200000000)
} ORDER BY DESC(?verdi) LIMIT 200

Spørsmål: Hvem er yngste spiller på hvert lag?
SPARQL:
PREFIX wc: <http://example.org/wc2026/ontology#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?lag ?navn ?født WHERE {
  { SELECT ?t (MAX(?d) AS ?født) WHERE {
      ?t wc:calledUp ?pp . ?pp wc:dateOfBirth ?d .
    } GROUP BY ?t }
  ?t rdfs:label ?lag ; wc:calledUp ?p .
  ?p wc:dateOfBirth ?født ; foaf:name ?navn .
} ORDER BY ?lag LIMIT 200
"""


def _strip_fences(text):
    """Fjern evt. ```-kodeblokk-markører Claude måtte legge på."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def to_sparql(question):
    """Oversett et norsk spørsmål til en SPARQL-spørring (ren tekst).

    Hever ValueError ved tomt spørsmål; lar anthropic-unntak boble opp.
    """
    if not question or not question.strip():
        raise ValueError("Tomt spørsmål.")
    msg = _get_client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=ONTOLOGY_SPEC,
        messages=[{"role": "user", "content": question.strip()}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")
    sparql = _strip_fences(text)
    if not sparql:
        raise ValueError("Klarte ikke å lage en SPARQL-spørring av spørsmålet.")
    return sparql


def _format_rows(content_type, body):
    """Lag en kompakt tekstgjengivelse av resultatet til oppsummerings-kallet."""
    if "sparql-results+json" not in (content_type or ""):
        # CONSTRUCT/DESCRIBE → turtle; send et utdrag.
        return (body or "")[:3000]
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return body or ""
    if "boolean" in data:
        return f"boolean = {data['boolean']}"
    vars_ = data.get("head", {}).get("vars", [])
    rows = data.get("results", {}).get("bindings", [])
    total = len(rows)
    lines = [" | ".join(vars_)]
    for row in rows[:SUMMARY_MAX_ROWS]:
        lines.append(" | ".join(str(row.get(v, {}).get("value", "")) for v in vars_))
    if total > SUMMARY_MAX_ROWS:
        lines.append(f"... ({total} rader totalt, viser {SUMMARY_MAX_ROWS})")
    return "\n".join(lines)


_SUMMARY_SYSTEM = (
    "Du oppsummerer resultatet av en SPARQL-spørring kort og presist på norsk for "
    "en bruker som stilte et spørsmål om VM 2026-tropper. Svar med 1–3 setninger. "
    "Bruk konkrete tall og navn fra dataene. Ikke gjenta SPARQL-en, og ikke finn "
    "på data utover det som står i resultatet."
)


def summarize(question, sparql, content_type, body):
    """Skriv et kort norsk svar basert på resultatradene. Returnerer "" ved feil."""
    rows_text = _format_rows(content_type, body)
    user = (
        f"Spørsmål: {question.strip()}\n\n"
        f"SPARQL:\n{sparql}\n\n"
        f"Resultat:\n{rows_text}"
    )
    try:
        msg = _get_client().messages.create(
            model=MODEL,
            max_tokens=512,
            system=_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception as exc:  # noqa: BLE001 – tekstsvar er «nice to have»
        log.warning("Oppsummering feilet: %s", exc)
        return ""

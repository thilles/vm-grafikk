"""Small hardcoded lookups used as a fallback / enrichment of article data.

Group letters are derived from the article's section structure; confederation
and the 3-letter codes are not reliably present in the squad tables, so they
live here. The 3-letter code doubles as the country URI code (a stable, unique
key across these 48 nations; FIFA codes are used where they differ from ISO3,
e.g. GER, NED, SUI, RSA — documented in README under the URI scheme).
"""

# nation display name (as it appears as a Wikipedia section heading) ->
# (FIFA 3-letter code, confederation)
NATIONS = {
    # Group A
    "Czech Republic": ("CZE", "UEFA"),
    "Mexico": ("MEX", "CONCACAF"),
    "South Africa": ("RSA", "CAF"),
    "South Korea": ("KOR", "AFC"),
    # Group B
    "Bosnia and Herzegovina": ("BIH", "UEFA"),
    "Canada": ("CAN", "CONCACAF"),
    "Qatar": ("QAT", "AFC"),
    "Switzerland": ("SUI", "UEFA"),
    # Group C
    "Brazil": ("BRA", "CONMEBOL"),
    "Haiti": ("HAI", "CONCACAF"),
    "Morocco": ("MAR", "CAF"),
    "Scotland": ("SCO", "UEFA"),
    # Group D
    "Australia": ("AUS", "AFC"),
    "Paraguay": ("PAR", "CONMEBOL"),
    "Turkey": ("TUR", "UEFA"),
    "United States": ("USA", "CONCACAF"),
    # Group E
    "Curaçao": ("CUW", "CONCACAF"),
    "Ecuador": ("ECU", "CONMEBOL"),
    "Germany": ("GER", "UEFA"),
    "Ivory Coast": ("CIV", "CAF"),
    # Group F
    "Japan": ("JPN", "AFC"),
    "Netherlands": ("NED", "UEFA"),
    "Sweden": ("SWE", "UEFA"),
    "Tunisia": ("TUN", "CAF"),
    # Group G
    "Belgium": ("BEL", "UEFA"),
    "Egypt": ("EGY", "CAF"),
    "Iran": ("IRN", "AFC"),
    "New Zealand": ("NZL", "OFC"),
    # Group H
    "Cape Verde": ("CPV", "CAF"),
    "Saudi Arabia": ("KSA", "AFC"),
    "Spain": ("ESP", "UEFA"),
    "Uruguay": ("URU", "CONMEBOL"),
    # Group I
    "France": ("FRA", "UEFA"),
    "Iraq": ("IRQ", "AFC"),
    "Norway": ("NOR", "UEFA"),
    "Senegal": ("SEN", "CAF"),
    # Group J
    "Algeria": ("ALG", "CAF"),
    "Argentina": ("ARG", "CONMEBOL"),
    "Austria": ("AUT", "UEFA"),
    "Jordan": ("JOR", "AFC"),
    # Group K
    "Colombia": ("COL", "CONMEBOL"),
    "DR Congo": ("COD", "CAF"),
    "Portugal": ("POR", "UEFA"),
    "Uzbekistan": ("UZB", "AFC"),
    # Group L
    "Croatia": ("CRO", "UEFA"),
    "England": ("ENG", "UEFA"),
    "Ghana": ("GHA", "CAF"),
    "Panama": ("PAN", "CONCACAF"),
}

# Position code -> human label for the controlled vocabulary.
POSITIONS = {
    "GK": "Goalkeeper",
    "DF": "Defender",
    "MF": "Midfielder",
    "FW": "Forward",
}

CONFEDERATIONS = {
    "UEFA": "Union of European Football Associations",
    "CONMEBOL": "South American Football Confederation",
    "CONCACAF": "Confederation of North, Central America and Caribbean Association Football",
    "CAF": "Confederation of African Football",
    "AFC": "Asian Football Confederation",
    "OFC": "Oceania Football Confederation",
}


def fifa_code(nation: str) -> str:
    return NATIONS.get(nation, (None, None))[0]


def confederation(nation: str) -> str:
    return NATIONS.get(nation, (None, None))[1]

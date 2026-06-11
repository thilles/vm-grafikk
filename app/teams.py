"""Lag-database for VM 2026: kanoniske navn, alias, flagg, gruppe og konføderasjon."""
import unicodedata

def norm(s):
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())

# canonical -> (norsk navn, flagg, gruppe, konføderasjon, aliaser)
TEAMS = {
    "Mexico":        ("Mexico", "🇲🇽", "A", "CONCACAF", []),
    "South Africa":  ("Sør-Afrika", "🇿🇦", "A", "CAF", ["Sor-Afrika"]),
    "South Korea":   ("Sør-Korea", "🇰🇷", "A", "AFC", ["Korea Republic", "Sor-Korea"]),
    "Czechia":       ("Tsjekkia", "🇨🇿", "A", "UEFA", ["Czech Republic"]),
    "Canada":        ("Canada", "🇨🇦", "B", "CONCACAF", []),
    "Bosnia and Herzegovina": ("Bosnia-Hercegovina", "🇧🇦", "B", "UEFA", ["Bosnia-Herzegovina", "Bosnia"]),
    "Switzerland":   ("Sveits", "🇨🇭", "B", "UEFA", []),
    "Qatar":         ("Qatar", "🇶🇦", "B", "AFC", []),
    "Brazil":        ("Brasil", "🇧🇷", "C", "CONMEBOL", []),
    "Morocco":       ("Marokko", "🇲🇦", "C", "CAF", []),
    "Haiti":         ("Haiti", "🇭🇹", "C", "CONCACAF", []),
    "Scotland":      ("Skottland", "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "C", "UEFA", []),
    "USA":           ("USA", "🇺🇸", "D", "CONCACAF", ["United States", "United States of America"]),
    "Paraguay":      ("Paraguay", "🇵🇾", "D", "CONMEBOL", []),
    "Australia":     ("Australia", "🇦🇺", "D", "AFC", []),
    "Türkiye":       ("Tyrkia", "🇹🇷", "D", "UEFA", ["Turkey", "Turkiye"]),
    "Germany":       ("Tyskland", "🇩🇪", "E", "UEFA", []),
    "Curaçao":       ("Curaçao", "🇨🇼", "E", "CONCACAF", ["Curacao"]),
    "Ivory Coast":   ("Elfenbenskysten", "🇨🇮", "E", "CAF", ["Cote d'Ivoire", "Elfenbenkysten"]),
    "Ecuador":       ("Ecuador", "🇪🇨", "E", "CONMEBOL", ["Equador"]),
    "Netherlands":   ("Nederland", "🇳🇱", "F", "UEFA", ["Holland"]),
    "Japan":         ("Japan", "🇯🇵", "F", "AFC", []),
    "Sweden":        ("Sverige", "🇸🇪", "F", "UEFA", []),
    "Tunisia":       ("Tunisia", "🇹🇳", "F", "CAF", []),
    "Belgium":       ("Belgia", "🇧🇪", "G", "UEFA", ["Beliga"]),
    "Egypt":         ("Egypt", "🇪🇬", "G", "CAF", []),
    "Iran":          ("Iran", "🇮🇷", "G", "AFC", ["IR Iran"]),
    "New Zealand":   ("New Zealand", "🇳🇿", "G", "OFC", []),
    "Spain":         ("Spania", "🇪🇸", "H", "UEFA", []),
    "Saudi Arabia":  ("Saudi-Arabia", "🇸🇦", "H", "AFC", ["Saudi Arabia"]),
    "Cape Verde":    ("Kapp Verde", "🇨🇻", "H", "CAF", ["Cabo Verde", "Kapp Verde", "Cape Verde Islands"]),
    "Uruguay":       ("Uruguay", "🇺🇾", "H", "CONMEBOL", []),
    "Norway":        ("Norge", "🇳🇴", "I", "UEFA", []),
    "France":        ("Frankrike", "🇫🇷", "I", "UEFA", []),
    "Iraq":          ("Irak", "🇮🇶", "I", "AFC", []),
    "Senegal":       ("Senegal", "🇸🇳", "I", "CAF", []),
    "Argentina":     ("Argentina", "🇦🇷", "J", "CONMEBOL", []),
    "Algeria":       ("Algerie", "🇩🇿", "J", "CAF", []),
    "Austria":       ("Østerrike", "🇦🇹", "J", "UEFA", ["Osterike", "Østerike"]),
    "Jordan":        ("Jordan", "🇯🇴", "J", "AFC", []),
    "Portugal":      ("Portugal", "🇵🇹", "K", "UEFA", []),
    "DR Congo":      ("DR Kongo", "🇨🇩", "K", "CAF", ["Congo DR", "DR Kongo", "Democratic Republic of the Congo"]),
    "Uzbekistan":    ("Usbekistan", "🇺🇿", "K", "AFC", []),
    "Colombia":      ("Colombia", "🇨🇴", "K", "CONMEBOL", []),
    "England":       ("England", "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "L", "UEFA", []),
    "Croatia":       ("Kroatia", "🇭🇷", "L", "UEFA", []),
    "Panama":        ("Panama", "🇵🇦", "L", "CONCACAF", []),
    "Ghana":         ("Ghana", "🇬🇭", "L", "CAF", []),
}

GROUPS = sorted({g for _, _, g, _, _ in TEAMS.values()})

_ALIAS_INDEX = {}
for canon, (no_name, flag, group, confed, aliases) in TEAMS.items():
    for a in [canon, no_name] + aliases:
        _ALIAS_INDEX[norm(a)] = canon

def canonical(name):
    """Slå opp kanonisk lagnavn fra norsk/engelsk navn eller alias. None hvis ukjent."""
    return _ALIAS_INDEX.get(norm(name))

def no_name(canon):
    return TEAMS[canon][0] if canon in TEAMS else canon

def flag(canon):
    return TEAMS[canon][1] if canon in TEAMS else "⚽"

def group_of(canon):
    return TEAMS[canon][2] if canon in TEAMS else None

def teams_in_group(letter):
    return [c for c, t in TEAMS.items() if t[2] == letter]

def is_african(canon):
    return canon in TEAMS and TEAMS[canon][3] == "CAF"

def display(canon):
    """Flagg + norsk navn for visning."""
    return f"{flag(canon)} {no_name(canon)}"

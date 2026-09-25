"""Immutable, city-only records shared by offline search and explicit geocoding."""
from dataclasses import dataclass
import unicodedata


LOCATION_VERSION = "travel-cities-v5"
COMPONENT_VERSION = 5


@dataclass(frozen=True)
class Airport:
    iata: str
    name: str
    source: str = "ourairports"
    association: str = "municipality"
    kind: str = ""


@dataclass(frozen=True)
class Location:
    id: str
    city: str
    region: str
    country: str
    country_code: str
    latitude: float | None
    longitude: float | None
    source: str
    airports: tuple[Airport, ...] = ()

    @property
    def label(self):
        parts = []
        # Regions remain structured data even where the display convention omits them.
        region = "" if self.country_code in {"fr", "jp", "ae"} else self.region
        for value in (self.city, region, self.country):
            if value and value.casefold() not in {part.casefold() for part in parts}:
                parts.append(value)
        return ", ".join(parts)

    @property
    def suggestion_label(self):
        # Size is a display hint, not a required airport or passenger-volume claim.
        ordered = sorted(self.airports, key=lambda airport: (
            airport.kind != "large_airport", airport.iata))
        codes = list(dict.fromkeys(airport.iata for airport in ordered))
        if not codes:
            return self.label
        suffix = " / ".join(codes[:3])
        if len(codes) > 3:
            suffix += f" (+{len(codes) - 3})"
        return f"{self.label} · {suffix}"

_STATE_ROWS = """
AL Alabama
AK Alaska
AZ Arizona
AR Arkansas
CA California
CO Colorado
CT Connecticut
DE Delaware
FL Florida
GA Georgia
HI Hawaii
ID Idaho
IL Illinois
IN Indiana
IA Iowa
KS Kansas
KY Kentucky
LA Louisiana
ME Maine
MD Maryland
MA Massachusetts
MI Michigan
MN Minnesota
MS Mississippi
MO Missouri
MT Montana
NE Nebraska
NV Nevada
NH New Hampshire
NJ New Jersey
NM New Mexico
NY New York
NC North Carolina
ND North Dakota
OH Ohio
OK Oklahoma
OR Oregon
PA Pennsylvania
RI Rhode Island
SC South Carolina
SD South Dakota
TN Tennessee
TX Texas
UT Utah
VT Vermont
VA Virginia
WA Washington
WV West Virginia
WI Wisconsin
WY Wyoming
DC District of Columbia
"""
US_STATES = {}
for _row in _STATE_ROWS.strip().splitlines():
    _code, _state = _row.split(" ", 1)
    US_STATES[_code.casefold()] = _state
    US_STATES[_state.casefold()] = _state
US_COUNTRY_NAMES = {"us", "usa", "united states", "united states of america"}


def normalize_text(value):
    if not isinstance(value, str):
        return ""
    return " ".join("".join(
        character for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    ).casefold().split())



def parse_location_query(query):
    query = " ".join(query.split()).casefold()
    parts = [part.strip() for part in query.split(",")]
    state = US_STATES.get(parts[1]) if len(parts) in (2, 3) else None
    if len(parts) == 3 and parts[2] not in US_COUNTRY_NAMES:
        state = None
    return parts, state


def canonical_query(value):
    """Make US abbreviations and full states share one cache entry."""
    parts, state = parse_location_query(value)
    if state:
        return f"{parts[0]}, {state.casefold()}, usa"
    return ", ".join(parts)

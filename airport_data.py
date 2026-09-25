"""Build-time, conservative associations between OurAirports and GeoNames cities.

No network access here. Airport codes are optional metadata, never a selected
destination or a promise of live service. No individual city/airport exceptions.
"""
import csv
from math import asin, cos, radians, sin, sqrt
import re

from location_model import normalize_text

AIRPORT_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"


def distance_km(lat1, lon1, lat2, lon2):
    a, b = radians(lat1), radians(lat2)
    value = sin((b - a) / 2) ** 2 + cos(a) * cos(b) * sin(radians(lon2 - lon1) / 2) ** 2
    return 12742 * asin(min(1, sqrt(value)))


def eligible_airport(row):
    return (row.get("type") in {"large_airport", "medium_airport"}
            and row.get("scheduled_service") == "yes"
            and re.fullmatch(r"[A-Z]{3}", row.get("iata_code", "")) is not None)


def match_city(db, text, country, latitude, longitude, keyword=False):
    name = normalize_text(text)
    if len(name) < 4:
        return None
    rows = db.execute("""
        SELECT c.id, c.latitude, c.longitude, c.population, n.is_primary
        FROM names n JOIN cities c ON c.id=n.city_id
        WHERE n.name=? AND c.country_code=?
    """, (name, country)).fetchall()
    candidates = []
    for city_id, lat, lon, population, primary in rows:
        distance = distance_km(latitude, longitude, lat, lon)
        # Keywords may describe a metro served across a region boundary, but
        # must be an exact city name/alias, a major city, and geographically near.
        if distance <= 120 and (not keyword or population >= 100000):
            candidates.append((not primary, distance, -population, city_id))
    candidates.sort()
    if not candidates:
        return None
    if len(candidates) > 1:
        first, second = candidates[:2]
        if first[0] == second[0] and abs(second[1] - first[1]) < 15:
            return None  # Ambiguous same-name places: omit, rather than guess.
    return candidates[0][3], candidates[0][1]


def add_airports(db, path):
    db.executescript("""
        CREATE TABLE airports (
            id TEXT PRIMARY KEY, iata TEXT, name TEXT, kind TEXT,
            country_code TEXT, latitude REAL, longitude REAL
        );
        CREATE TABLE city_airports (
            city_id TEXT, airport_id TEXT, evidence TEXT, distance_km REAL,
            PRIMARY KEY (city_id, airport_id)
        ) WITHOUT ROWID;
    """)
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if not eligible_airport(row):
                continue
            try:
                lat, lon = float(row["latitude_deg"]), float(row["longitude_deg"])
            except (ValueError, KeyError):
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            country = row["iso_country"].lower()
            db.execute("INSERT INTO airports VALUES (?,?,?,?,?,?,?)", (
                row["ident"], row["iata_code"], row["name"], row["type"], country, lat, lon,
            ))
            # Parentheses describe airport localities, e.g. a suburb of the served city.
            municipality = re.sub(r"\([^)]*\)", "", row.get("municipality", "")).strip()
            terms = [(municipality, "municipality")]
            terms += [(word.strip(), "keyword") for word in row.get("keywords", "").split(",")]
            for term, evidence in terms:
                match = match_city(db, term, country, lat, lon, keyword=evidence == "keyword")
                if match:
                    city_id, distance = match
                    db.execute("INSERT OR IGNORE INTO city_airports VALUES (?,?,?,?)",
                               (city_id, row["ident"], evidence, round(distance, 2)))
    return db.execute("SELECT count(*) FROM city_airports").fetchone()[0]

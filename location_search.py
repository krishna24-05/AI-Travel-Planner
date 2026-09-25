"""Local travel-city search: primary names, major cities and airport connections."""
from contextlib import closing
from functools import lru_cache
from pathlib import Path
import sqlite3

import location_model

COMPONENT_VERSION = 5
INDEX_PATH = Path(__file__).resolve().parent / "data" / "locations" / "cities.sqlite3"
MIN_CHARACTERS = 3


class LocationIndexError(Exception):
    """Offline suggestions are temporarily unavailable."""


def suggest_locations(query):
    if not isinstance(query, str) or len(query.strip()) > 200:
        return ()
    query = location_model.canonical_query(query)
    if len(query.split(",", 1)[0].strip()) < MIN_CHARACTERS:
        return ()
    try:
        return _suggest_cached(query, str(INDEX_PATH), INDEX_PATH.stat().st_mtime_ns,
                               location_model.LOCATION_VERSION)
    except (OSError, sqlite3.Error):
        raise LocationIndexError("City suggestions are unavailable right now. Please try again shortly.") from None


def _qualifiers(parts, state):
    filters, values = [], []
    if state:
        filters.extend(["c.country_code = 'us'", "c.region_key = ?"])
        values.append(location_model.normalize_text(state))
    else:
        for qualifier in parts[1:]:
            normalized = location_model.normalize_text(qualifier)
            if normalized in location_model.US_COUNTRY_NAMES:
                filters.append("c.country_code = 'us'")
            else:
                filters.append("(c.region_key = ? OR c.country_key = ? OR c.country_code = ?)")
                values.extend([normalized] * 3)
    return filters, values


def rank_candidates(rows):
    """Population and administrative/airport evidence are proxies, not tourism stats.

    Do not fill the menu with tiny places just because they share a prefix.
    A specific smaller airport-served destination remains searchable by its name.
    """
    eligible = [row for row in rows if row["population"] >= 50000
                or row["airport_count"] > 0 or row["feature_code"] == "PPLC"
                or (row["feature_code"] == "PPLA" and row["population"] >= 10000)]
    strong = [row for row in eligible if row["match_rank"] <= 1 and row["population"] >= 100000]
    if strong:
        # Do not pad a clear primary-name search with unrelated alternate names.
        eligible = [row for row in eligible if row["match_rank"] <= 1 and (
                    row["population"] >= 50000
                    or (row["match_rank"] == 0 and row["population"] >= 25000))]
    eligible.sort(key=lambda row: (
        row["match_rank"], -row["population"],
        -int(row["feature_code"] in {"PPLC", "PPLA"}),
        -row["airport_count"], row["city"], row["id"],
    ))
    return eligible[:5]


@lru_cache(maxsize=512)
def _suggest_cached(query, path, data_version, version):
    parts, state = location_model.parse_location_query(query)
    prefix = location_model.normalize_text(parts[0])
    if any(not part for part in parts):
        return ()
    filters, values = _qualifiers(parts, state)
    constraints = "".join(" AND " + clause for clause in filters)
    with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if db.execute("PRAGMA user_version").fetchone()[0] != 4:
            raise sqlite3.DatabaseError("The city index requires a rebuild.")
        rows = db.execute("""
            SELECT c.*, MIN(CASE
                WHEN n.is_primary=1 AND n.name=? THEN 0
                WHEN n.is_primary=1 THEN 1
                WHEN n.name=? THEN 2 ELSE 3 END) AS match_rank,
                (SELECT count(*) FROM city_airports a WHERE a.city_id=c.id) AS airport_count
            FROM names n JOIN cities c ON c.id=n.city_id
            WHERE n.name>=? AND n.name<?
        """ + constraints + " GROUP BY c.id", [prefix, prefix, prefix, prefix + "\U0010ffff", *values]).fetchall()
        ranked = rank_candidates(rows)
        if not ranked and len(prefix) >= 4:
            # Substrings never displace a useful prefix match. Scan only primary names.
            rows = db.execute("""
                SELECT c.*, 4 AS match_rank,
                    (SELECT count(*) FROM city_airports a WHERE a.city_id=c.id) AS airport_count
                FROM cities c WHERE instr(c.primary_key, ?) > 0
            """ + constraints, [prefix, *values]).fetchall()
            ranked = rank_candidates(rows)
        results = []
        for row in ranked:
            airports = tuple(location_model.Airport(a[0], a[1], association=a[2], kind=a[3]) for a in db.execute("""
                SELECT a.iata, a.name, ca.evidence, a.kind
                FROM city_airports ca JOIN airports a ON a.id=ca.airport_id
                WHERE ca.city_id=? ORDER BY a.iata
            """, (row["id"],)))
            results.append(location_model.Location(
                id=f"geonames:{row['id']}", city=row["city"], region=row["region"],
                country=row["country"], country_code=row["country_code"],
                latitude=row["latitude"], longitude=row["longitude"], source="geonames", airports=airports,
            ))
    return tuple(results)

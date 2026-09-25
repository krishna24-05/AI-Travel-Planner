"""Offline association safeguards, including an audit of the bundled global index."""
from contextlib import closing
import sqlite3
import unittest

from airport_data import eligible_airport, match_city
from location_search import INDEX_PATH


class AirportDataTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE cities(id TEXT, latitude REAL, longitude REAL,
                                population INTEGER, country_code TEXT);
            CREATE TABLE names(name TEXT, city_id TEXT, is_primary INTEGER);
        """)

    def city(self, identifier, lat=0, lon=0, population=200000, country="aa"):
        self.db.execute("INSERT INTO cities VALUES (?,?,?,?,?)",
                        (identifier, lat, lon, population, country))
        self.db.execute("INSERT INTO names VALUES ('example city',?,1)", (identifier,))

    def test_only_scheduled_medium_or_large_iata_airports(self):
        valid = dict(type="large_airport", scheduled_service="yes", iata_code="ABC")
        self.assertTrue(eligible_airport(valid))
        self.assertTrue(eligible_airport({**valid, "type": "medium_airport"}))
        for changes in ({"type": "heliport"}, {"type": "small_airport"},
                        {"scheduled_service": "no"}, {"iata_code": ""}, {"iata_code": "AB12"}):
            self.assertFalse(eligible_airport({**valid, **changes}))

    def test_same_name_requires_same_country_and_geographic_proximity(self):
        self.city("near")
        self.city("foreign", country="bb")
        self.city("distant", lat=20)
        self.assertEqual(match_city(self.db, "Example City", "aa", 0, 0)[0], "near")
        self.assertIsNone(match_city(self.db, "Example City", "cc", 0, 0))
        self.assertIsNone(match_city(self.db, "Example City", "aa", 40, 40))

    def test_ambiguous_same_name_is_omitted(self):
        self.city("first")
        self.city("second", lon=0.01)
        self.assertIsNone(match_city(self.db, "Example City", "aa", 0, 0))

    def test_keyword_associations_require_major_city_and_exact_name(self):
        self.city("small", population=20000)
        self.assertIsNone(match_city(self.db, "Example City", "aa", 0, 0, keyword=True))
        self.assertIsNotNone(match_city(self.db, "Example City", "aa", 0, 0))
        self.assertIsNone(match_city(self.db, "Example", "aa", 0, 0))

    def test_global_index_association_invariants(self):
        with closing(sqlite3.connect(INDEX_PATH.as_uri() + "?mode=ro", uri=True)) as db:
            self.assertGreater(db.execute("SELECT count(*) FROM city_airports").fetchone()[0], 2000)
            invalid = db.execute("""
                SELECT count(*) FROM city_airports ca
                LEFT JOIN cities c ON c.id=ca.city_id
                LEFT JOIN airports a ON a.id=ca.airport_id
                WHERE c.id IS NULL OR a.id IS NULL OR c.country_code<>a.country_code
                   OR ca.distance_km>120 OR ca.distance_km<0
                   OR a.kind NOT IN ('medium_airport','large_airport')
                   OR length(a.iata)<>3
                   OR ca.evidence NOT IN ('municipality','keyword')
                   OR (ca.evidence='keyword' AND c.population<100000)
            """).fetchone()[0]
            self.assertEqual(invalid, 0)

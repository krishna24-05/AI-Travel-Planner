from dataclasses import FrozenInstanceError
import unittest
from unittest.mock import patch

from location_model import Location
from location_search import MIN_CHARACTERS, _suggest_cached, suggest_locations


class OfflineSearchTests(unittest.TestCase):
    def setUp(self):
        # A typing search must never hit an external endpoint, even on a cache miss.
        blocker = patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network call"))
        blocker.start()
        self.addCleanup(blocker.stop)
        _suggest_cached.cache_clear()

    def test_required_cities_and_state_spellings(self):
        for query, label in (
            ("Detroit, MI", "Detroit, Michigan, USA"),
            ("Detroit, Michigan", "Detroit, Michigan, USA"),
            ("Chicago, IL", "Chicago, Illinois, USA"),
            ("Chicago, Illinois", "Chicago, Illinois, USA"),
            ("Hyderabad, India", "Hyderabad, Telangana, India"),
            ("Hyderabad", "Hyderabad, Telangana, India"),
        ):
            with self.subTest(query=query):
                self.assertEqual(suggest_locations(query)[0].label, label)
        for query in ("Paris", "Paris, France"):
            result = suggest_locations(query)[0]
            self.assertEqual((result.city, result.country), ("Paris", "France"))

    def test_prefix_returns_small_ranked_city_list(self):
        results = suggest_locations("Detr")
        self.assertLessEqual(len(results), 5)
        self.assertEqual(results[0].label, "Detroit, Michigan, USA")
        self.assertEqual([item.city for item in results], ["Detroit"])
        self.assertTrue(all(item.source == "geonames" for item in results))

    def test_empty_short_nonsense_and_business_queries(self):
        for query in ("", "De", "zzqxqnonexistent", "Detroit Forming, Inc.", "Chicago restaurant", "Detroit, Illinois"):
            with self.subTest(query=query):
                self.assertEqual(suggest_locations(query), ())
        self.assertEqual(MIN_CHARACTERS, 3)

    def test_selection_is_structured_immutable_and_clean(self):
        record = suggest_locations("Detroit, MI")[0]
        self.assertIsInstance(record, Location)
        self.assertEqual(record.country_code, "us")
        self.assertTrue(record.id.startswith("geonames:"))
        self.assertIsInstance(record.latitude, float)
        self.assertNotIn("County", record.label)
        with self.assertRaises(FrozenInstanceError):
            record.city = "Detroit Forming, Inc."

    def test_equivalent_queries_share_cache(self):
        first = suggest_locations("Detroit, MI")
        self.assertIs(suggest_locations("  DETROIT, Michigan  "), first)
        self.assertEqual(_suggest_cached.cache_info().misses, 1)
        self.assertEqual(_suggest_cached.cache_info().hits, 1)

    def test_explicit_foreign_country_not_interpreted_as_us_state(self):
        self.assertEqual(suggest_locations("Paris, France")[0].country_code, "fr")
        self.assertEqual(suggest_locations("Hyderabad, Telangana, India")[0].region, "Telangana")

    def test_major_travel_prefixes_and_airports(self):
        for query, label, code in (
            ("Detr", "Detroit, Michigan, USA", "DTW"),
            ("Detroit", "Detroit, Michigan, USA", "DTW"),
            ("Chic", "Chicago, Illinois, USA", "ORD"),
            ("Par", "Paris, France", "CDG"),
            ("Hyd", "Hyderabad, Telangana, India", "HYD"),
            ("Los", "Los Angeles, California, USA", "LAX"),
        ):
            with self.subTest(query=query):
                results = suggest_locations(query)
                self.assertEqual(results[0].label, label)
                self.assertIn(code, {airport.iata for airport in results[0].airports})
                self.assertIn(code, results[0].suggestion_label)
                self.assertNotIn(code, results[0].label)
                self.assertLessEqual(len(results), 5)

    def test_global_city_airport_associations(self):
        for query, label, codes in (
            ("Toronto", "Toronto, Ontario, Canada", {"YYZ", "YTZ"}),
            ("London", "London, England, United Kingdom", {"LHR", "LGW", "LCY"}),
            ("Rome", "Rome, Lazio, Italy", {"FCO", "CIA"}),
            ("Tokyo", "Tokyo, Japan", {"HND", "NRT"}),
            ("Dubai", "Dubai, United Arab Emirates", {"DXB", "DWC"}),
            ("Bengaluru", "Bengaluru, Karnataka, India", {"BLR"}),
            ("Mumbai", "Mumbai, Maharashtra, India", {"BOM"}),
            ("Sydney", "Sydney, New South Wales, Australia", {"SYD"}),
        ):
            with self.subTest(query=query):
                result = suggest_locations(query)[0]
                self.assertEqual(result.label, label)
                self.assertTrue(codes.issubset({airport.iata for airport in result.airports}))

    def test_primary_matches_are_not_padded_with_weak_aliases(self):
        self.assertTrue(all(item.city == "Hyderabad" for item in suggest_locations("Hyd")))
        self.assertTrue(all(item.city.startswith("London") for item in suggest_locations("London")))
        self.assertNotIn("Lomé", [item.city for item in suggest_locations("Rome")])
        self.assertEqual(suggest_locations("Bangalore")[0].city, "Bengaluru")

    def test_multiple_airports_remain_separate_city_metadata(self):
        record = suggest_locations("New York")[0]
        self.assertTrue({"JFK", "LGA", "EWR"}.issubset({a.iata for a in record.airports}))
        self.assertEqual(record.label, "New York City, New York, USA")
        self.assertIn("EWR / JFK / LGA", record.suggestion_label)
        self.assertIsInstance(record.airports, tuple)
        with self.assertRaises(FrozenInstanceError):
            record.airports[0].iata = "XXX"

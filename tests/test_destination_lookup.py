import unittest
from unittest.mock import patch

import requests
import destination_lookup as lookup


def city_result(city="Detroit", state="Michigan", country="United States", code="us"):
    return {
        "category": "boundary", "type": "administrative", "addresstype": "city",
        "name": city, "display_name": f"{city}, Unnecessary County, {state}, {country}",
        "address": {"city": city, "state": state, "country": country, "country_code": code},
    }


def business_result():
    return {
        "category": "office", "type": "company", "addresstype": "office",
        "name": "Detroit Forming, Inc.",
        "display_name": "Detroit Forming, Inc., 15 Sagamore Park Road, Hudson, New Hampshire",
        "address": {"town": "Hudson", "state": "New Hampshire",
                    "country": "United States", "country_code": "us"},
    }


class LookupTests(unittest.TestCase):
    def setUp(self):
        lookup._lookup_cached.cache_clear()
        self.addCleanup(lookup._lookup_cached.cache_clear)
        request_patch = patch("destination_lookup.requests.get")
        self.get = request_patch.start()
        self.addCleanup(request_patch.stop)
        sleep_patch = patch("destination_lookup.time.sleep")
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def test_us_city_spellings_and_structured_requests(self):
        for query, city, state in (
            ("Detroit, MI", "Detroit", "Michigan"),
            ("Detroit, Michigan", "Detroit", "Michigan"),
            ("Chicago, IL", "Chicago", "Illinois"),
            ("Chicago, Illinois", "Chicago", "Illinois"),
            ("Detroit, MI, USA", "Detroit", "Michigan"),
        ):
            with self.subTest(query=query):
                lookup._lookup_cached.cache_clear()
                self.get.return_value.json.return_value = [city_result(city, state)]
                self.assertEqual(lookup.lookup_destination(query), f"{city}, {state}, USA")
                params = self.get.call_args.kwargs["params"]
                self.assertEqual(params["city"], city.lower())
                self.assertEqual(params["state"], state)
                self.assertEqual(params["countrycodes"], "us")
                self.assertNotIn("q", params)
                self.assertEqual(params["featureType"], "settlement")
                self.assertEqual(params["addressdetails"], 1)
                self.assertGreater(params["limit"], 1)

    def test_business_rejected_even_with_matching_city_in_address(self):
        for candidate in (business_result(), {**business_result(), "address": city_result()["address"]}):
            lookup._lookup_cached.cache_clear()
            self.get.return_value.json.return_value = [candidate]
            self.assertIsNone(lookup.lookup_destination("Detroit, MI"))

    def test_valid_city_selected_after_business_and_wrong_state(self):
        self.get.return_value.json.return_value = [business_result(), city_result(state="Oregon"), city_result()]
        self.assertEqual(lookup.lookup_destination("Detroit, MI"), "Detroit, Michigan, USA")

    def test_mismatched_places_rejected(self):
        for candidate in (city_result(state="Oregon"), city_result(city="Detroit Lakes"),
                          city_result(country="Canada", code="ca")):
            lookup._lookup_cached.cache_clear()
            self.get.return_value.json.return_value = [candidate]
            self.assertIsNone(lookup.lookup_destination("Detroit, MI"))

    def test_international_city_and_local_name_alias(self):
        candidate = city_result("Lisbon", "Lisbon", "Portugal", "pt")
        candidate["namedetails"] = {"name": "Lisboa", "name:en": "Lisbon"}
        self.get.return_value.json.return_value = [candidate]
        for query in ("Lisbon, Portugal", "Lisboa, Portugal"):
            self.assertEqual(lookup.lookup_destination(query), "Lisbon, Portugal")
            self.assertNotIn("countrycodes", self.get.call_args.kwargs["params"])
        self.assertIsNone(lookup.lookup_destination("Lisbon, Spain"))

    def test_town_and_village(self):
        for kind in ("town", "village", "municipality"):
            lookup._lookup_cached.cache_clear()
            candidate = city_result("Sintra", "Lisbon", "Portugal", "pt")
            candidate.update(category="place", type=kind, addresstype=kind)
            candidate["address"][kind] = candidate["address"].pop("city")
            self.get.return_value.json.return_value = [candidate]
            self.assertEqual(lookup.lookup_destination("Sintra, Portugal"), "Sintra, Lisbon, Portugal")

    def test_nonsense_empty_and_malformed_candidates(self):
        self.assertIsNone(lookup.lookup_destination("  "))
        self.get.assert_not_called()
        for results in ([], [city_result()], [None, {}, {"display_name": "made-up"}]):
            lookup._lookup_cached.cache_clear()
            self.get.return_value.json.return_value = results
            self.assertIsNone(lookup.lookup_destination("zzqxxnonsense"))

    def test_service_errors(self):
        for error in (requests.Timeout(), ValueError("invalid json")):
            self.get.return_value.json.side_effect = error
            with self.assertRaises(lookup.DestinationLookupError):
                lookup.lookup_destination("Detroit, MI")
        self.get.return_value.json.side_effect = None
        self.get.return_value.json.return_value = {"error": "invalid response"}
        with self.assertRaises(lookup.DestinationLookupError):
            lookup.lookup_destination("Detroit, MI")

    def test_cache_and_rate_limit(self):
        self.get.return_value.json.return_value = [city_result()]
        with patch("destination_lookup.time.monotonic", return_value=10), patch.object(lookup, "_last_request_time", 9.5), patch("destination_lookup.time.sleep") as sleep:
            lookup.lookup_destination("Detroit, MI")
            lookup.lookup_destination("  DETROIT, MI  ")
            lookup.lookup_destination("Detroit, Michigan")
            self.get.assert_called_once()
            sleep.assert_called_once_with(0.5)

    def test_cache_expires(self):
        self.get.return_value.json.return_value = [city_result()]
        with patch("destination_lookup.time.time", return_value=1):
            lookup.lookup_destination("Detroit, MI")
        with patch("destination_lookup.time.time", return_value=lookup._CACHE_TTL + 1):
            lookup.lookup_destination("Detroit, Michigan")
        self.assertEqual(self.get.call_count, 2)

    def test_structured_results_filter_businesses(self):
        self.get.return_value.json.return_value = [business_result(), city_result()]
        result = lookup.search_locations("Detroit, Michigan")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].label, "Detroit, Michigan, USA")
        self.assertEqual(result[0].source, "nominatim")

    def test_paris_and_hyderabad(self):
        for city, state, country, code in (("Paris", "Ile-de-France", "France", "fr"),
                                           ("Hyderabad", "Telangana", "India", "in")):
            self.get.return_value.json.return_value = [city_result(city, state, country, code)]
            expected = f"{city}, {country}" if code == "fr" else f"{city}, {state}, {country}"
            self.assertEqual(lookup.lookup_destination(f"{city}, {country}"), expected)

    def test_diagnostic_shows_order_and_bypasses_cache(self):
        self.get.return_value.json.return_value = [business_result(), city_result()]
        lookup.lookup_destination("Detroit, MI")
        report = lookup.inspect_location("Detroit, Michigan")
        self.assertEqual(self.get.call_count, 2)
        self.assertTrue(report["cache_bypassed"])
        self.assertEqual(report["parameters"]["state"], "Michigan")
        self.assertIsNone(report["ordered_candidates"][0]["accepted_label"])
        self.assertEqual(report["ordered_candidates"][1]["accepted_label"], "Detroit, Michigan, USA")

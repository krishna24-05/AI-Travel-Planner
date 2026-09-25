from datetime import date
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx2 as httpx
from openai import APIConnectionError, APIStatusError, AuthenticationError, RateLimitError
from planner import OPENAI_MODEL, ItineraryGenerationError, calculate_trip_days, generate_itinerary
from streamlit.testing.v1 import AppTest
import destination_lookup
from location_model import Location


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.trip = {
            "origin": "Detroit", "destination": "Paris",
            "departure_date": date(2026, 9, 10), "return_date": date(2026, 9, 12),
            "trip_days": 3, "travelers": 2, "total_budget": 900,
            "interests": ["Museums", "Nature"], "transportation_percent": 40,
        }
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": "test-placeholder"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.factory_patch = patch("planner.OpenAI")
        self.factory = self.factory_patch.start()
        self.addCleanup(self.factory_patch.stop)
        self.client = self.factory.return_value.__enter__.return_value
        self.client.responses.create.return_value = SimpleNamespace(
            status="completed", output_text="# Trip Overview\nA personalized trip."
        )

    def test_inclusive_dates_across_month_and_leap_day(self):
        self.assertEqual(calculate_trip_days(date(2028, 2, 28), date(2028, 3, 1)), 3)

    def test_same_day_and_reverse_dates_rejected(self):
        for end in (date(2026, 9, 10), date(2026, 9, 9)):
            with self.assertRaises(ValueError):
                calculate_trip_days(date(2026, 9, 10), end)

    def test_markdown_and_all_trip_details_without_mutating_input(self):
        original = dict(self.trip)
        result = generate_itinerary(self.trip)
        self.assertEqual(result, "# Trip Overview\nA personalized trip.")
        args = self.client.responses.create.call_args.kwargs
        self.assertEqual(args["model"], OPENAI_MODEL)
        self.assertFalse(args["store"])
        sent = json.loads(args["input"].split("\n", 1)[1])
        for field, value in self.trip.items():
            self.assertEqual(sent[field], value.isoformat() if isinstance(value, date) else value)
        self.assertEqual(self.trip, original)
        self.assertNotIn("test-placeholder", args["input"] + args["instructions"])
        self.factory.assert_called_once_with(api_key="test-placeholder", timeout=120.0, max_retries=1)

    def test_missing_or_blank_key_does_not_call_api(self):
        for key in (None, "", "   "):
            with patch.dict(os.environ):
                if key is None:
                    os.environ.pop("OPENAI_API_KEY", None)
                else:
                    os.environ["OPENAI_API_KEY"] = key
                with self.assertRaisesRegex(ItineraryGenerationError, "not configured"):
                    generate_itinerary(self.trip)
        self.factory.assert_not_called()

    def test_budget_constraints_use_existing_reserve_and_group_totals(self):
        from decimal import Decimal
        for total, percentage, reserve, remaining in (
            (1200, 30, 360, 840),
            (123.47, 35, 43.21, 80.26),
            (900, 0, 0, 900),
            (900, 100, 900, 0),
        ):
            with self.subTest(total=total, percentage=percentage):
                trip = {**self.trip, "total_budget": total, "transportation_percent": percentage}
                generate_itinerary(trip)
                sent = json.loads(self.client.responses.create.call_args.kwargs["input"].split("\n", 1)[1])
                constraints = sent["budget_constraints"]
                self.assertEqual(constraints["round_trip_transportation_reserve"], reserve)
                self.assertEqual(constraints["destination_budget"], remaining)
                self.assertEqual(Decimal(str(reserve)) + Decimal(str(remaining)), Decimal(str(total)))
                self.assertEqual(constraints["accommodation_nights"], 2)
                self.assertTrue(constraints["amounts_are_for_entire_group"])
                self.assertEqual(constraints["daily_spending_excludes"],
                                 ["round-trip transportation", "accommodation", "emergency buffer"])
                self.assertNotIn("budget_constraints", trip)

    def test_default_reserve_and_nights_across_month_boundary(self):
        trip = {**self.trip, "departure_date": date(2028, 2, 28),
                "return_date": date(2028, 3, 1)}
        del trip["transportation_percent"]
        generate_itinerary(trip)
        sent = json.loads(self.client.responses.create.call_args.kwargs["input"].split("\n", 1)[1])
        self.assertEqual(sent["transportation_percent"], 30)
        self.assertEqual(sent["budget_constraints"]["round_trip_transportation_reserve"], 270)
        self.assertEqual(sent["budget_constraints"]["destination_budget"], 630)
        self.assertEqual(sent["budget_constraints"]["accommodation_nights"], 2)

    def test_invalid_trip_is_rejected_before_api(self):
        for changes in ({"trip_days": 2}, {"interests": []}, {"travelers": 0}, {"total_budget": 0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                generate_itinerary({**self.trip, **changes})
        self.factory.assert_not_called()

    def test_empty_or_incomplete_response_is_not_displayed(self):
        for status, text in (("completed", "  "), ("incomplete", "Partial plan"), ("failed", "")):
            self.client.responses.create.return_value = SimpleNamespace(status=status, output_text=text)
            with self.assertRaisesRegex(ItineraryGenerationError, "Please try again"):
                generate_itinerary(self.trip)

    def test_sdk_failures_have_safe_messages(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        private_message = "sensitive-request-details"
        for error_type, status, expected in (
            (AuthenticationError, 401, "configuration"),
            (RateLimitError, 429, "quota"),
            (APIStatusError, 500, "try again"),
        ):
            error = error_type(private_message, response=httpx.Response(status, request=request), body=None)
            self.client.responses.create.side_effect = error
            with self.subTest(status=status), self.assertRaises(ItineraryGenerationError) as caught:
                generate_itinerary(self.trip)
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn(private_message, str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)
        self.client.responses.create.side_effect = APIConnectionError(request=request)
        with self.assertRaisesRegex(ItineraryGenerationError, "try again"):
            generate_itinerary(self.trip)


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        destination_lookup._lookup_cached.cache_clear()
        self.addCleanup(lambda: destination_lookup._lookup_cached.cache_clear())
        self.events = {}
        component = patch("streamlit_searchbox._get_react_component", side_effect=self.component_event)
        self.component = component.start()
        self.addCleanup(component.stop)
        network = patch("destination_lookup.requests.get", side_effect=AssertionError("Unexpected geocoding request"))
        self.get = network.start()
        self.addCleanup(network.stop)
        factory = patch("planner.OpenAI")
        self.factory = factory.start()
        self.addCleanup(factory.stop)

    def component_event(self, **kwargs):
        field = "origin" if kwargs["key"].startswith("location_origin_") else "destination"
        return self.events.pop(field, None)

    def send_event(self, app, field, interaction, value):
        self.events[field] = {"interaction": interaction, "value": value}
        app.run()
        self.assertFalse(app.exception)

    def choose(self, app, field, query):
        self.send_event(app, field, "search", query)
        self.send_event(app, field, "submit", 0)

    def make_app(self, selected=True):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
        self.assertFalse(app.exception)
        if selected:
            self.choose(app, "origin", "Detroit, MI")
            self.choose(app, "destination", "Chicago, Illinois")
        app.multiselect[0].set_value(["Museums"])
        return app

    def test_selected_locations_pass_clean_names_to_openai(self):
        with patch("planner.os") as environment:
            environment.environ.get.return_value = "test-placeholder"
            factory = self.factory
            client = factory.return_value.__enter__.return_value
            client.responses.create.return_value = SimpleNamespace(status="completed", output_text="# Trip Overview\nChicago plan")
            app = self.make_app()
            app.date_input[0].set_value(date(2026, 10, 10))
            app.date_input[1].set_value(date(2026, 10, 12))
            app.number_input[0].set_value(2)
            app.number_input[1].set_value(1200.0)
            app.multiselect[0].set_value(["Food & Restaurants", "Museums", "Hidden Gems"])
            app.button(key="craft_trip").click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            sent = json.loads(client.responses.create.call_args.kwargs["input"].split("\n", 1)[1])
            self.assertEqual(sent["origin"], "Detroit, Michigan, USA")
            self.assertEqual(sent["destination"], "Chicago, Illinois, USA")
            self.assertEqual(sent["trip_days"], 3)
            self.assertEqual(sent["transportation_percent"], 30)
            self.assertEqual(sent["travelers"], 2)
            self.assertEqual(sent["total_budget"], 1200)
            self.assertIsInstance(app.session_state["location_origin_selected"], Location)
            self.get.assert_not_called()

    def test_business_match_prevents_generation(self):
        app = self.make_app(selected=False)
        self.send_event(app, "origin", "search", "Detroit Forming, Inc.")
        self.assertEqual(app.session_state["location_origin_search_0"]["options_py"], [])
        app.button(key="craft_trip").click().run()
        self.assertTrue(app.error)
        self.factory.assert_not_called()
        self.get.assert_not_called()

    def test_lookup_unavailable_preserves_friendly_error(self):
        from location_search import LocationIndexError
        app = self.make_app(selected=False)
        message = "City suggestions are unavailable right now. Please try again shortly."
        with patch("location_widgets.suggest_locations", side_effect=LocationIndexError(message)):
            self.send_event(app, "origin", "search", "Detroit")
        self.assertIn(message, [caption.value for caption in app.caption])
        self.factory.assert_not_called()

    def test_validated_trip_displays_markdown_and_survives_rerun(self):
        with patch("planner.generate_itinerary", return_value="# Trip Overview\nPersonalized plan") as generate:
            app = self.make_app()
            app.button(key="craft_trip").click().run()
            self.assertFalse(app.exception)
            self.get.assert_not_called()
            self.assertEqual(generate.call_args.args[0]["origin"], "Detroit, Michigan, USA")
            self.assertTrue(any("Personalized plan" in element.value for element in app.markdown))
            app.run()
            generate.assert_called_once()
            self.assertTrue(any("Personalized plan" in element.value for element in app.markdown))

    def test_unknown_location_prevents_generation(self):
        with patch("planner.generate_itinerary") as generate:
            app = self.make_app(selected=False)
            self.send_event(app, "origin", "search", "zzqxqnonsense")
            app.button(key="craft_trip").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            generate.assert_not_called()

    def test_generation_errors_are_friendly(self):
        for error in (ItineraryGenerationError("OpenAI API access is not configured yet."), RuntimeError("private-configuration")):
            with self.subTest(error=type(error).__name__), patch("planner.generate_itinerary", side_effect=error):
                app = self.make_app()
                app.button(key="craft_trip").click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
                self.assertNotIn("private-configuration", app.error[0].value)
                self.assertNotIn("planned_trip", app.session_state)

    def test_clear_and_new_search_invalidate_selection(self):
        app = self.make_app()
        self.send_event(app, "origin", "reset", None)
        self.assertIsNone(app.session_state["location_origin_selected"])
        app.button(key="craft_trip").click().run()
        self.factory.assert_not_called()
        self.choose(app, "origin", "Detroit, Michigan")
        self.send_event(app, "origin", "search", "Paris")
        self.assertIsNone(app.session_state["location_origin_selected"])
        app.button(key="craft_trip").click().run()
        self.factory.assert_not_called()

    def test_typing_is_local_and_debounced(self):
        app = self.make_app(selected=False)
        for query in ("D", "De", "Det", "Detr"):
            self.send_event(app, "origin", "search", query)
        options = app.session_state["location_origin_search_0"]["options_py"]
        self.assertEqual(options[0].label, "Detroit, Michigan, USA")
        self.assertLessEqual(len(options), 5)
        self.assertEqual(self.component.call_args.kwargs["debounce"], 300)
        self.get.assert_not_called()
        self.factory.assert_not_called()

    def test_trip_inputs_survive_location_changes(self):
        app = self.make_app()
        app.date_input[0].set_value(date(2026, 10, 10))
        app.date_input[1].set_value(date(2026, 10, 12))
        app.number_input[0].set_value(2)
        app.number_input[1].set_value(1200.0)
        app.slider[0].set_value(45)
        app.multiselect[0].set_value(["Museums", "Hidden Gems"])
        app.run()
        self.send_event(app, "origin", "reset", None)
        self.choose(app, "origin", "Paris, France")
        self.assertEqual(app.date_input[0].value, date(2026, 10, 10))
        self.assertEqual(app.date_input[1].value, date(2026, 10, 12))
        self.assertEqual(app.number_input[0].value, 2)
        self.assertEqual(app.number_input[1].value, 1200.0)
        self.assertEqual(app.slider[0].value, 45)
        self.assertEqual(app.multiselect[0].value, ["Museums", "Hidden Gems"])

    def test_legacy_planned_trip_is_removed(self):
        app = self.make_app(selected=False)
        app.session_state["location_version"] = "old"
        app.session_state["planned_trip"] = ({"origin": "Detroit Forming, Inc."}, "old plan")
        app.run()
        self.assertFalse(app.exception)
        self.assertNotIn("planned_trip", app.session_state)

    def test_no_manual_fallback_in_either_field(self):
        app = self.make_app(selected=False)
        self.assertFalse(app.text_input)
        self.assertFalse(app.selectbox)
        self.assertFalse(any("Can't find your city?" in item.label for item in app.expander))

    def test_airport_metadata_does_not_replace_selected_city(self):
        app = self.make_app()
        origin = app.session_state["location_origin_selected"]
        destination = app.session_state["location_destination_selected"]
        self.assertEqual(origin.label, "Detroit, Michigan, USA")
        self.assertIn("DTW", {airport.iata for airport in origin.airports})
        self.assertTrue({"ORD", "MDW"}.issubset({airport.iata for airport in destination.airports}))
        app.run()
        self.assertEqual(app.session_state["location_origin_selected"], origin)
        self.get.assert_not_called()
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()


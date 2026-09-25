"""Offline presentation and navigation regressions; never call a real provider."""
from datetime import date, timedelta
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from budget import calculate_budget
from location_search import suggest_locations
from presentation import SECTION_NAMES, budget_allocations, split_days, split_sections, split_transport_options


def itinerary(days=3):
    bodies = ["A thoughtful city break.", "Budget-friendly option to investigate: bus.",
              "| Category | USD |\n| --- | --- |\n| Transportation | 330 |\n| Destination | 770 |",
              "".join(f"## Day {i} — September {i}\n- Morning: Explore {i}.\n- Afternoon: Museum.\n- Evening: Rest.\n- Food suggestion: Local dish.\n- Local transportation: Walk.\n- Approximate daily/group spending: USD 20.\n" for i in range(1, days+1)),
              "- Verify fares and availability directly.\n- Pack comfortable shoes."]
    return "\n".join(f"# {title}\n{body}" for title, body in zip(SECTION_NAMES, bodies))


class PresentationTests(unittest.TestCase):
    def test_calculated_bars_reconcile_without_subtotal_double_counting(self):
        from decimal import Decimal
        budget = calculate_budget(1000, 3, 2, 30)
        self.assertEqual(budget["transportation"], 300)
        self.assertEqual(budget["destination_budget"], 700)
        self.assertEqual(dict(budget_allocations(budget)), {
            "Round-trip transportation": 300, "Accommodation": 280,
            "Food": 175, "Local transportation": 105, "Activities": 140})
        for total in (1000, 123.47, .01):
            for reserve in (0, 30, 100):
                allocations = budget_allocations(calculate_budget(total, 3, 2, reserve))
                self.assertEqual(sum(Decimal(str(v)) for _, v in allocations), Decimal(str(total)))

    def test_transport_cards_preserve_generated_modes_and_descriptions(self):
        text = ('- **Budget-friendly option to investigate:** Ferry\n  Consider transfers.\n\n'
                '- **Alternative to investigate:** Coach\n  Check baggage.\nVerify availability.')
        cards = split_transport_options(text)
        self.assertEqual(len(cards), 2)
        self.assertIn('Ferry\n  Consider transfers.', cards[0][1])
        self.assertIn('Coach\n  Check baggage.\nVerify availability.', cards[1][1])
        for unexpected in ('Unstructured advice.', 'Intro\n' + text,
                           text.split('\n\n')[0], text.replace('Alternative to investigate', 'Other route')):
            self.assertIsNone(split_transport_options(unexpected))

    def test_sections_preserve_every_body(self):
        text = itinerary()
        sections = split_sections(text)
        reconstructed = "".join(f"# {title}\n{body}" for title, body in sections.items())
        self.assertEqual(reconstructed, text)

    def test_unexpected_contract_falls_back(self):
        for text in ("Freeform content", "Introduction\n" + itinerary(),
                     itinerary().replace("# Budget", "# Costs"), itinerary() + "\n# Extra\nAdvice"):
            self.assertIsNone(split_sections(text))

    def test_days_preserve_content_and_check_coverage(self):
        body = split_sections(itinerary(15))["Day-by-Day Itinerary"]
        days = split_days(body, 15)
        self.assertEqual(len(days), 15)
        self.assertIn("Explore 15.", days[-1][1])
        self.assertIsNone(split_days(body, 3))
        self.assertIsNone(split_days("Arrival assumption\n" + body, 15))
        self.assertIsNone(split_days(body.replace("Day 2 —", "Day 1 —"), 15))

    def test_required_city_labels_and_budget(self):
        for query, label in (("Detr", "Detroit, Michigan, USA · DTW"),
                             ("Chic", "Chicago, Illinois, USA · MDW / ORD"),
                             ("Par", "Paris, France · CDG / ORY"),
                             ("Hyd", "Hyderabad, Telangana, India · HYD"),
                             ("Los", "Los Angeles, California, USA · LAX")):
            self.assertEqual(suggest_locations(query)[0].suggestion_label, label)
        budget = calculate_budget(1100, 3, 2, 30)
        self.assertEqual(budget["transportation"], 330)
        self.assertEqual(budget["transportation"] + budget["destination_budget"], 1100)

    @patch("planner.generate_itinerary", return_value=itinerary())
    def test_edit_preserves_all_inputs_without_regeneration(self, generate):
        with patch("streamlit_searchbox._get_react_component", return_value=None):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
            app.session_state["location_origin_selected"] = suggest_locations("Detr")[0]
            app.session_state["location_destination_selected"] = suggest_locations("Par")[0]
            # Remount the custom widgets with the structured selections as defaults.
            app.session_state["location_origin_generation"] = 1
            app.session_state["location_destination_generation"] = 1
            app.date_input[0].set_value(date(2026, 10, 10))
            app.date_input[1].set_value(date(2026, 10, 12))
            app.number_input[0].set_value(2)
            app.number_input[1].set_value(1100.0)
            app.multiselect[0].set_value(["Museums", "Art"])
            app.slider[0].set_value(30)
            app.run()
            app.button(key="craft_trip").click().run()
            self.assertFalse(app.exception)
            app.run()
            app.button(key="edit_trip").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.date_input[0].value, date(2026, 10, 10))
            self.assertEqual(app.date_input[1].value, date(2026, 10, 12))
            self.assertEqual(app.number_input[0].value, 2)
            self.assertEqual(app.number_input[1].value, 1100)
            self.assertEqual(app.multiselect[0].value, ["Museums", "Art"])
            self.assertEqual(app.slider[0].value, 30)
            self.assertEqual(app.session_state["location_origin_selected"].city, "Detroit")
            self.assertEqual(app.session_state["location_destination_selected"].city, "Paris")
            generate.assert_called_once()

    @patch("planner.OpenAI", side_effect=AssertionError("Real generation forbidden"))
    def test_short_long_and_fallback_results(self, factory):
        for count, text in ((3, itinerary()), (15, itinerary(15)), (3, "Unexpected but valuable content")):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
            trip = dict(origin="Detroit, Michigan, USA", destination="Paris, France",
                        departure_date=date(2026, 9, 1), return_date=date(2026, 9, 1)+timedelta(days=count-1),
                        trip_days=count, travelers=2, total_budget=1100, transportation_percent=30,
                        interests=["Museums", "Nature", "Art"])
            app.session_state["planned_trip"] = (trip, text)
            app.run()
            self.assertFalse(app.exception)
            if count == 15:
                self.assertEqual(len(app.expander), 15)
            elif text.startswith("#"):
                self.assertEqual(len(app.tabs), 3)
            else:
                self.assertTrue(any(text in md.value for md in app.markdown))
            app.button(key="edit_trip").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["planned_trip"], (trip, text))
            app.button(key="view_trip").click().run()
            self.assertFalse(app.exception)
        factory.assert_not_called()

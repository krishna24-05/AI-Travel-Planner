"""Isolated interpreter checks for cold imports and stale Streamlit modules."""
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class LocationImportTests(unittest.TestCase):
    def run_isolated(self, code):
        result = subprocess.run(
            [sys.executable, "-B", "-c", textwrap.dedent(code)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_offline_ui_does_not_import_geocoder_or_planner(self):
        self.run_isolated('''
            import sys
            from importlib.abc import MetaPathFinder
            class BlockProviders(MetaPathFinder):
                def find_spec(self, fullname, *args):
                    if fullname in {"destination_lookup", "planner", "openai"}:
                        raise AssertionError("Unexpected provider import: " + fullname)
            sys.meta_path.insert(0, BlockProviders())
            from location_runtime import load_location_widgets
            widgets = load_location_widgets()
            import location_model, location_search
            assert widgets.COMPONENT_VERSION == 5
            assert location_search.suggest_locations("Detroit, Michigan")[0].label == "Detroit, Michigan, USA"
            assert "destination_lookup" not in sys.modules
        ''')

    def test_stale_dependency_chain_is_refreshed_before_consumers(self):
        self.run_isolated('''
            import sys
            from types import ModuleType
            for name in ("location_model", "location_search", "location_widgets", "destination_lookup"):
                sys.modules[name] = ModuleType(name)
            from location_runtime import load_location_widgets, load_geocoder
            widgets = load_location_widgets()
            assert widgets.COMPONENT_VERSION == 5
            import location_search, location_model
            assert isinstance(location_search.suggest_locations("Chicago, IL")[0], location_model.Location)
            assert not hasattr(sys.modules["destination_lookup"], "search_locations")
            provider = load_geocoder()
            assert callable(provider.search_locations)
            assert callable(provider.inspect_location)
            assert provider.COMPONENT_VERSION == 5
        ''')

    def test_missing_api_is_repaired_even_with_current_version_marker(self):
        self.run_isolated('''
            import sys
            from types import ModuleType
            legacy = ModuleType("destination_lookup")
            legacy.COMPONENT_VERSION = 5
            sys.modules["destination_lookup"] = legacy
            from location_runtime import load_geocoder
            assert callable(load_geocoder().search_locations)
        ''')

    def test_normal_reruns_preserve_class_identity_and_search_cache(self):
        self.run_isolated('''
            from location_runtime import load_location_widgets
            first = load_location_widgets()
            import location_model, location_search
            record = location_search.suggest_locations("Detroit, MI")[0]
            cls = location_model.Location
            assert load_location_widgets() is first
            assert location_model.Location is cls
            assert location_search.suggest_locations("Detroit, Michigan")[0] is record
        ''')

"""Load the location interface in dependency order, including legacy reruns.

Python retains imported modules between Streamlit reruns. Refresh incompatible
modules before importing their consumers, not after a consumer's import fails.
No provider or OpenAI client is loaded by the offline UI bootstrap.
"""
from importlib import import_module, invalidate_caches, reload
from threading import RLock

COMPONENT_VERSION = 5
_VERSION = COMPONENT_VERSION
_lock = RLock()


def _load(name, required, force=False):
    module = import_module(name)
    outdated = getattr(module, "COMPONENT_VERSION", None) != _VERSION
    missing = any(not hasattr(module, member) for member in required)
    refreshed = force or outdated or missing
    if refreshed:
        module = reload(module)
    if getattr(module, "COMPONENT_VERSION", None) != _VERSION or any(
        not hasattr(module, member) for member in required
    ):
        raise ImportError(f"Incompatible location module: {name}. Please update all location files together.")
    return module, refreshed


def load_location_widgets():
    with _lock:
        invalidate_caches()
        _, model_changed = _load("location_model", ("Location", "canonical_query", "parse_location_query"))
        _, search_changed = _load("location_search", ("suggest_locations", "LocationIndexError"), model_changed)
        widgets, _ = _load("location_widgets", ("location_picker", "migrate_location_state"),
                           model_changed or search_changed)
        return widgets


def load_geocoder():
    """Load optional explicit search only after the user requests it."""
    with _lock:
        invalidate_caches()
        _, changed = _load("location_model", ("Location", "canonical_query", "parse_location_query"))
        provider, _ = _load("destination_lookup", ("search_locations", "DestinationLookupError", "inspect_location"), changed)
        return provider

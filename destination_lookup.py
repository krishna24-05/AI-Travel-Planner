"""Look up destinations with OpenStreetMap's public Nominatim service."""

import os
import time
from functools import lru_cache
from threading import Lock

import requests
import location_model

COMPONENT_VERSION = 5


# Allow switching providers without changing the code.
GEOCODING_URL = os.getenv(
    "GEOCODING_URL", "https://nominatim.openstreetmap.org/search"
)
_lookup_lock = Lock()
_last_request_time = 0.0
_CACHE_TTL = 24 * 60 * 60

_LOCALITY_TYPES = {"city", "town", "village", "hamlet", "municipality"}

def _search_parameters(query):
    parts, state = location_model.parse_location_query(query)
    query = ", ".join(parts)
    params = {"format": "jsonv2", "limit": 10, "addressdetails": 1,
              "namedetails": 1, "featureType": "settlement"}
    if state:
        params.update(city=parts[0], state=state, countrycodes="us")
    else:
        params["q"] = query
    return params, parts, state


def _city_location(result, parts, requested_state):
    if not isinstance(result, dict):
        return None
    category = result.get("category", result.get("class"))
    kind = result.get("addresstype", result.get("type"))
    # A POI may contain a city in its address; that does not make it a city.
    if kind not in _LOCALITY_TYPES or not (
        category == "place" and result.get("type") in _LOCALITY_TYPES
        or category == "boundary" and result.get("type") == "administrative"
    ):
        return None
    address = result.get("address")
    if not isinstance(address, dict):
        return None
    city = address.get(kind) or result.get("name")
    country = address.get("country")
    if not location_model.normalize_text(city) or not location_model.normalize_text(country):
        return None
    names = {location_model.normalize_text(city), location_model.normalize_text(result.get("name"))}
    details = result.get("namedetails")
    if isinstance(details, dict):
        for key, value in details.items():
            if key in {"name", "official_name", "short_name", "alt_name"} or key.startswith("name:"):
                if isinstance(value, str):
                    names.update(location_model.normalize_text(name) for name in value.split(";"))
    if location_model.normalize_text(parts[0]) not in names:
        return None
    state = address.get("state", "")
    is_us = location_model.normalize_text(address.get("country_code")) == "us"
    if requested_state:
        if not is_us or location_model.US_STATES.get(location_model.normalize_text(state)) != requested_state:
            return None
        state = requested_state
    else:
        qualifiers = {location_model.normalize_text(value) for key, value in address.items()
                      if key not in {"road", "house_number", "postcode"} and isinstance(value, str)}
        if is_us:
            qualifiers.update(location_model.US_COUNTRY_NAMES)
        if any(not part or location_model.normalize_text(part) not in qualifiers for part in parts[1:]):
            return None
    if is_us:
        country = "USA"
        state = location_model.US_STATES.get(location_model.normalize_text(state), state)
    return location_model.Location(
        id=f"nominatim:{result.get('osm_type', '')}:{result.get('osm_id', result.get('place_id', city))}",
        city=city.strip(), region=state.strip() if isinstance(state, str) else "",
        country=country.strip(), country_code=location_model.normalize_text(address.get("country_code")),
        latitude=_coordinate(result.get("lat")), longitude=_coordinate(result.get("lon")),
        source="nominatim",
    )


def _coordinate(value):
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _city_label(result, parts, requested_state):
    location = _city_location(result, parts, requested_state)
    return location.label if location else None


class DestinationLookupError(Exception):
    """The service could not reliably check a destination."""


def lookup_destination(destination):
    """Return a validated city/region/country label, or None if no city matches.

    Raise DestinationLookupError when the service is unavailable.
    The lock shares the rate limit across sessions in this app process.
    """
    locations = search_locations(destination)
    return locations[0].label if locations else None


def search_locations(destination):
    """Explicit, user-submitted searches only. Never call from autocomplete."""
    query = location_model.canonical_query(destination)
    if not query:
        return ()

    with _lookup_lock:
        return _lookup_cached(query, location_model.LOCATION_VERSION, GEOCODING_URL, int(time.time() // _CACHE_TTL))


@lru_cache(maxsize=256)
def _lookup_cached(query, version, endpoint, epoch):
    results = _request_results(query, endpoint)
    _, parts, state = _search_parameters(query)
    locations = []
    seen = set()
    for result in results:
        location = _city_location(result, parts, state)
        if location and location.id not in seen:
            locations.append(location)
            seen.add(location.id)
    return tuple(locations[:5])


def _request_results(query, endpoint):
    """Caller holds the process-wide lock, including during diagnostics."""
    global _last_request_time

    wait_seconds = 1.0 - (time.monotonic() - _last_request_time)
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    _last_request_time = time.monotonic()
    params, parts, state = _search_parameters(query)
    try:
        response = requests.get(
            endpoint,
            params=params,
            headers={"User-Agent": "AI-Travel-Planner/1.0", "Accept-Language": "en"},
            timeout=10,
        )
        response.raise_for_status()
        results = response.json()
    except (requests.RequestException, ValueError) as error:
        raise DestinationLookupError("Destination lookup is unavailable.") from error

    if not isinstance(results, list):
        raise DestinationLookupError("Unexpected destination lookup response.")
    return results


def inspect_location(destination):
    """Fresh, rate-limited response for the CLI; does not use cached labels."""
    query = location_model.canonical_query(destination)
    params, parts, state = _search_parameters(query)
    with _lookup_lock:
        results = _request_results(query, GEOCODING_URL)
    candidates = []
    for result in results:
        if not isinstance(result, dict):
            continue
        candidates.append({
            **{key: result.get(key) for key in (
                "name", "category", "class", "type", "addresstype", "display_name", "address"
            )},
            "accepted_label": _city_label(result, parts, state),
        })
    return {"query": destination, "canonical_query": query, "parameters": params,
            "cache_bypassed": True, "location_version": location_model.LOCATION_VERSION,
            "ordered_candidates": candidates}

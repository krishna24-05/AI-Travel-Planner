# Location selection

Both trip fields use `streamlit-searchbox` with a 300 ms debounce and a three-character
minimum city prefix. Searches use the bundled GeoNames SQLite index, with a bounded
512-entry cache. Typing makes no external requests. There is no manual-location
fallback in either field.

## Travel-focused ranking

Primary exact city names rank before primary prefixes, then alternate names.
Population orders equally matching cities, followed by administrative and airport
evidence. Useful primary matches suppress weaker aliases; substring matching runs
only when no useful prefix matches exist. State/country constraints apply first,
and US state abbreviations and full names share a canonical query.

Candidates normally need population of 50,000, an associated scheduled-service
airport, or capital/administrative-seat evidence. When a primary match has at least
100,000 residents, tiny matches and alternate-name padding are suppressed. Menus
contain at most five results; fewer are preferable to irrelevant padding.
Population and airport service are travel proxies, not tourism popularity statistics.
No individual city examples are hard-coded.

## City selection and airport metadata

Each selection is an immutable city record: source ID, city, region, country,
country code, coordinates, and a separate tuple of airport records. Airport records
retain IATA, name, source, size classification, and association evidence.
Only the clean city label reaches `planner.py`; submission never geocodes it again.
Search/clear invalidates the old selection. Version migration clears legacy location
and generated-trip state while preserving native trip inputs.

Suggestions show up to three airport codes, with a count for additional airports.
Large airports precede medium airports; codes within each size group are alphabetical,
not a statement of preference or required airport. Thus Chicago displays MDW / ORD
and Paris displays CDG / ORY. France, Japan, and UAE display labels omit the region,
which remains available in the structured record.

The existing OurAirports snapshot is public domain. Build-time matching requires
a scheduled-service medium/large airport, valid IATA, exact municipality or city
alias, matching country, and distance within 120 km. Keyword-based metropolitan
associations additionally require population of 100,000. Ambiguous nearby same-name
cities are omitted. These conservative rules can miss airports where source
municipalities are inconsistent or metropolitan relationships are undocumented;
this is not a complete airport routing dataset and does not promise current service.

## Styling

Component-scoped overrides keep the input, iframe background, and dropdown white
or pale blush with dark burgundy text, including when the host theme is dark.
Mouse hover, keyboard focus, and selection use pale blush. These rules do not alter
the rest of the page. The browser check covers the pinned searchbox component's DOM.

## Verification without OpenAI

Run the full automated suite (external services mocked):

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Run the optional real-server/browser check with dev-only Playwright and local Chrome:

```powershell
.venv/Scripts/python.exe -B scripts/check_streamlit_startup.py
```

This starts `streamlit run app.py` on a temporary local port with a dark host theme,
checks typing, selection, clearing, readable colors and keyboard focus, and stops
only its own server. It never presses Craft My Trip or changes API-key configuration.
Screenshots go to ignored `.artifacts/`. Playwright is not a runtime dependency.

`destination_lookup.py` and `scripts/check_locations.py` remain standalone
Nominatim diagnostics, separate from autocomplete. They are not invoked by either
location field. Public Nominatim prohibits autocomplete; the local search does not
use it. Run the diagnostic script only for explicit provider investigation.

## Data and imports

See [dataset documentation](data/locations/README.md) for attribution, snapshot
hashes and refresh instructions. The existing prepared schema-v4 database is reused.
Database timestamp changes invalidate cached searches.

`location_runtime.py` loads model, local search and widgets in dependency order,
checking component versions and APIs before loading consumers. Normal reruns preserve
class identity and caches. Component version 5 refreshes pre-interruption modules;
location state version `travel-cities-v5` invalidates old selections.
The optional diagnostic geocoder has a separate loader and is not imported by the UI.

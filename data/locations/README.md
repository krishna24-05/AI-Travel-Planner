# Offline city and airport index

`cities.sqlite3` is a prepared derivative of GeoNames cities1000, first-level
administrative names, and country names. Attribution: [GeoNames](https://www.geonames.org/),
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Source: https://download.geonames.org/export/dump/

Airport metadata comes from [OurAirports](https://ourairports.com/data/),
released into the public domain. The cached source CSV is approximately 12.7 MB
(86,112 rows); 3,244 scheduled-service medium/large IATA airports are retained.
The prepared index contains 160,943 cities and 2,730 conservative city/airport links.
Source hashes and the snapshot build date are in `metadata.json`.

Changes: retained current populated places and administrative seats; removed other
feature types; normalized aliases; joined country and region names; rendered United
States as USA; associated airports using exact city names/aliases, country, distance,
and municipality/keyword evidence. No individual cities or airports are hard-coded.

Coverage includes cities above 1,000 residents and qualifying administrative seats,
but runtime travel ranking suppresses minor places. Some destinations and airport
associations are absent, and source data can be incomplete or outdated. Airport codes
are supplemental information, not required airports or live service/pricing.
See [location behavior](../../LOCATION_SYSTEM.md) for ranking and matching rules.

Build/update deliberately from the project root:

```powershell
.venv/Scripts/python.exe scripts/build_location_index.py
# Fetch a new snapshot (never done during startup or typing):
.venv/Scripts/python.exe scripts/build_location_index.py --refresh
```

The builder uses the standard library and existing requests dependency. Downloaded
source files are ignored by Git. Include the prepared database in deployments.
A temporary database replaces the old one only after a successful build.

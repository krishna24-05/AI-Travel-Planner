"""Build the offline index; never called by the app or during typing.

Run: python scripts/build_location_index.py
Sources are downloaded once into data/locations/source/ and reused. To refresh,
run with --refresh. No OpenAI modules or credentials are used.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import zipfile

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from location_model import normalize_text
from airport_data import AIRPORT_URL, add_airports

ROOT = Path(__file__).resolve().parents[1] / "data" / "locations"
SOURCE_URL = "https://download.geonames.org/export/dump/"
SOURCES = ("cities1000.zip", "admin1CodesASCII.txt", "countryInfo.txt")
# Populated places and administrative seats only, excluding abandoned/historical
# places, sections of cities, buildings, farms, and other point features.
CITY_CODES = {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC", "PPLG"}


def build(refresh=False):
    source_dir = ROOT / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for filename in SOURCES:
        path = source_dir / filename
        if refresh or not path.exists():
            response = requests.get(SOURCE_URL + filename, timeout=120,
                                    headers={"User-Agent": "AI-Travel-Planner/2.0"})
            response.raise_for_status()
            path.write_bytes(response.content)
        hashes[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
    airport_path = source_dir / "airports.csv"
    if refresh or not airport_path.exists():
        response = requests.get(AIRPORT_URL, timeout=120,
                                headers={"User-Agent": "AI-Travel-Planner/2.0"})
        response.raise_for_status()
        airport_path.write_bytes(response.content)
    hashes["airports.csv"] = hashlib.sha256(airport_path.read_bytes()).hexdigest()
    regions = {}
    for line in (source_dir / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        regions[fields[0]] = fields[1]
    countries = {}
    for line in (source_dir / "countryInfo.txt").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            fields = line.split("\t")
            countries[fields[0]] = fields[4]

    output = ROOT / "cities.sqlite3"
    temporary = ROOT / "cities.build.sqlite3"
    with closing(sqlite3.connect(temporary)) as db, db:
        db.executescript("""
            DROP TABLE IF EXISTS city_airports; DROP TABLE IF EXISTS airports;
            DROP TABLE IF EXISTS names; DROP TABLE IF EXISTS cities;
            CREATE TABLE cities (
                id TEXT PRIMARY KEY, city TEXT, region TEXT, country TEXT,
                country_code TEXT, latitude REAL, longitude REAL,
                population INTEGER, region_key TEXT, country_key TEXT,
                feature_code TEXT, primary_key TEXT
            );
            CREATE TABLE names (name TEXT, city_id TEXT, is_primary INTEGER,
                                PRIMARY KEY (name, city_id)) WITHOUT ROWID;
        """)
        with zipfile.ZipFile(source_dir / "cities1000.zip") as archive:
            with archive.open("cities1000.txt") as raw:
                for line in io.TextIOWrapper(raw, encoding="utf-8"):
                    row = line.rstrip("\n").split("\t")
                    if row[6] != "P" or row[7] not in CITY_CODES:
                        continue
                    city_id, city, ascii_name, aliases = row[:4]
                    code = row[8]
                    country = "USA" if code == "US" else countries.get(code, "")
                    region = regions.get(f"{code}.{row[10]}", "")
                    if not city or not country:
                        continue
                    db.execute("INSERT INTO cities VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                        city_id, city, region, country, code.lower(), float(row[4]),
                        float(row[5]), int(row[14] or 0), normalize_text(region), normalize_text(country),
                        row[7], normalize_text(city),
                    ))
                    primary_names = {normalize_text(city), normalize_text(ascii_name)}
                    names = {normalize_text(name) for name in aliases.split(",")
                             if 3 <= len(name) <= 120
                             and not (len(name) == 3 and name.isascii() and name.isupper())}
                    names.update(primary_names)
                    db.executemany("INSERT OR IGNORE INTO names VALUES (?,?,?)",
                                   ((name, city_id, int(name in primary_names)) for name in names if name))
        count = db.execute("SELECT count(*) FROM cities").fetchone()[0]
        associations = add_airports(db, airport_path)
        db.execute("PRAGMA user_version = 4")
    temporary.replace(output)
    metadata = {"source": SOURCE_URL, "license": "CC BY 4.0", "built_at": datetime.now(timezone.utc).isoformat(),
                "cities": count, "sha256": hashes, "schema_version": 4,
                "airports": {"source": AIRPORT_URL, "license": "Public domain", "associations": associations}}
    (ROOT / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Built {count:,} populated places in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    build(parser.parse_args().refresh)

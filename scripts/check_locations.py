"""Inspect live Nominatim results safely, without importing planner or OpenAI."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from destination_lookup import DestinationLookupError, inspect_location


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("locations", nargs="+", help='Example: "Detroit, MI" "Detroit, Michigan"')
    args = parser.parse_args()
    failed = False
    for query in args.locations:
        try:
            print(json.dumps(inspect_location(query), ensure_ascii=True, indent=2))
        except DestinationLookupError as error:
            print(json.dumps({"query": query, "error": str(error)}))
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

"""Build the reusable compact Larimer GeoPackage from an inclusive export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from flm_pipeline.larimer_compact import COMPACT_FILENAME, compact_network  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inclusive", type=Path, required=True, help="verified inclusive GeoPackage")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--boundary-bbox", type=float, nargs=4, metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"), help="explicit export boundary; omission preserves all prune candidates")
    parser.add_argument("--osm-extraction", type=Path, help="matching OSM extraction directory for vehicle-access pruning")
    parser.add_argument("--osm-classification", type=Path, help="matching OSM classification directory for vehicle-access pruning")
    parser.add_argument("--retain-osm-tags", action="store_true", help="export walking-relevant OSM fields and only merge lines with matching values")
    args = parser.parse_args()
    report = compact_network(
        args.inclusive, args.destination, boundary_bbox=args.boundary_bbox,
        osm_extraction=args.osm_extraction, osm_classification=args.osm_classification,
        retain_osm_tags=args.retain_osm_tags,
    )
    print(json.dumps({"status": report["status"], "path": str(args.destination / COMPACT_FILENAME), **report["output"]["layer_counts"]}, indent=2))


if __name__ == "__main__":
    main()

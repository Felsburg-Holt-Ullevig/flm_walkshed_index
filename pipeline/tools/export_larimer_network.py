"""Export the checked Larimer network to two GeoPackage layers."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from flm_pipeline.larimer_export import FILENAME, export_network  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-verification", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    evidence = json.loads(args.phase1_verification.read_text(encoding="utf-8"))
    report = export_network(ROOT / evidence["graph_report"], args.destination, evidence["example"]["candidate_id"])
    print(json.dumps({"path": str(args.destination / FILENAME), **report["layer_counts"]}))


if __name__ == "__main__":
    main()

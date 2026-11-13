"""Build one local, immutable walk-tile release from the accepted Denver package."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))
from flm_pipeline.walk_tiles import WalkTilesError, build_tiles  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args(argv)
    if re.fullmatch(r"[A-Za-z0-9_-]+", args.release_id) is None:
        parser.error("release ID may contain only letters, digits, hyphens and underscores")
    destination = ROOT / "data/generated/prototype/walk-tiles" / args.release_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        print(f"ERROR: destination already exists; refusing overwrite: {destination}", file=sys.stderr)
        return 2
    temp = Path(tempfile.mkdtemp(prefix=f".{args.release_id}-", dir=destination.parent))
    try:
        result = build_tiles(ROOT, temp, args.release_id, source_root=ROOT)
        if destination.exists():
            raise WalkTilesError(f"destination appeared during build; refusing overwrite: {destination}")
        os.rename(temp, destination)
        print(f"Built and verified: {destination}")
        print(f"Tiles: {result['verification']['tile_count']}; unique segments: {result['verification']['unique_segments']}; copies: {result['verification']['segment_copies']}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}\nTemporary output retained at: {temp}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

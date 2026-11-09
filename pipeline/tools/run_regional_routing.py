"""Run the local Task 4.4 regional diagnostic or prepare its expanded graph."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from flm_pipeline.regional_routing import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

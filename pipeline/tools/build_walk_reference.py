"""Build the approved six offline Step 3 reference cases."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from flm_pipeline.walk_reference_output import main

if __name__ == "__main__":
    raise SystemExit(main())

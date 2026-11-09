"""Stable identity for the offline pipeline implementation and its contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


_PIPELINE_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _PIPELINE_DIR.parent


def code_identity() -> dict[str, Any]:
    """Hash a sorted manifest, including untracked implementation files."""
    paths = [
        *_PIPELINE_DIR.joinpath("src").rglob("*.py"),
        *_PIPELINE_DIR.joinpath("tests").rglob("*.py"),
        _PIPELINE_DIR / "pyproject.toml",
        *_PIPELINE_DIR.glob("requirements*.lock.txt"),
        _PIPELINE_DIR / "source-network-contract.md",
        _PIPELINE_DIR / "google-earth-inspection-spec.md",
        _PIPELINE_DIR / "routing-graph-contract.md",
    ]
    manifest = [
        {
            "path": path.relative_to(_REPO_ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(set(paths), key=lambda item: item.relative_to(_REPO_ROOT).as_posix())
        if path.is_file()
    ]
    serialized = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {
        "algorithm": "pipeline-file-manifest-sha256-1",
        "sha256": hashlib.sha256(serialized).hexdigest(),
        "manifest": manifest,
    }

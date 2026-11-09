"""Runtime checks and package/native-library version reporting."""

from __future__ import annotations

import importlib.metadata
import platform
from pathlib import Path
import re
import sys
from typing import Any


REQUIRED_DISTRIBUTIONS = (
    "geopandas",
    "jsonschema",
    "osmium",
    "psutil",
    "pyogrio",
    "pyproj",
    "pytest",
    "setuptools",
    "shapely",
)
_PIPELINE_DIR = Path(__file__).resolve().parents[2]
_LOCK_FILES = (
    _PIPELINE_DIR / "requirements-win-py312.lock.txt",
    _PIPELINE_DIR / "requirements-package-win-py312.lock.txt",
    _PIPELINE_DIR / "requirements-bootstrap-win-py312.lock.txt",
)


def pinned_versions() -> dict[str, str]:
    """Read exact versions from both pip hash locks."""
    versions: dict[str, str] = {}
    requirement = re.compile(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)(?:\s+\\)?$")
    for lock_path in _LOCK_FILES:
        for line in lock_path.read_text(encoding="utf-8").splitlines():
            match = requirement.fullmatch(line.strip())
            if match:
                normalized = re.sub(r"[-_.]+", "-", match.group(1)).lower()
                versions[normalized] = match.group(2)
    return versions


def installed_versions() -> dict[str, str]:
    return {
        re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower(): distribution.version
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }


def runtime_errors(
    implementation: str | None = None,
    version: tuple[int, int, int] | None = None,
    system: str | None = None,
    machine: str | None = None,
) -> list[str]:
    implementation = implementation or sys.implementation.name
    version = version or sys.version_info[:3]
    system = system or platform.system()
    machine = machine or platform.machine()
    errors = []
    if implementation != "cpython":
        errors.append(f"Expected CPython; found {implementation}")
    if tuple(version) != (3, 12, 14):
        errors.append(f"Expected Python 3.12.14; found {'.'.join(map(str, version))}")
    if system != "Windows" or machine.lower() not in {"amd64", "x86_64"}:
        errors.append(f"Expected Windows x86-64; found {system} {machine}")
    return errors


def distribution_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for name in REQUIRED_DISTRIBUTIONS:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "missing"
    return result


def runtime_versions() -> dict[str, Any]:
    try:
        locked = {name: version for name, version in sorted(pinned_versions().items())}
    except OSError:
        locked = {}
    versions: dict[str, Any] = {
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "distributions": distribution_versions(),
        "locked_distributions": locked,
    }
    try:
        import osmium

        versions["libosmium"] = getattr(osmium, "__version__", "version not exposed by the Python module")
    except ImportError:
        versions["libosmium"] = "unavailable"
    try:
        import pyogrio

        versions["gdal"] = getattr(pyogrio, "__gdal_version_string__", "unknown")
    except ImportError:
        versions["gdal"] = "unavailable"
    try:
        import pyproj

        versions["proj"] = pyproj.proj_version_str
    except ImportError:
        versions["proj"] = "unavailable"
    try:
        import shapely

        versions["geos"] = shapely.geos_version_string
    except ImportError:
        versions["geos"] = "unavailable"
    return versions


def environment_errors() -> list[str]:
    errors = runtime_errors()
    versions = distribution_versions()
    errors.extend(f"Required package is missing: {name}" for name, version in versions.items() if version == "missing")
    try:
        expected = pinned_versions()
    except OSError as error:
        expected = {}
        errors.append(f"Could not read the Python lock files: {error}")
    if not expected:
        errors.append("Python lock files contain no exact version pins")
    actual = installed_versions()
    for name, expected_version in expected.items():
        actual_version = actual.get(name)
        if actual_version != expected_version:
            errors.append(f"Locked package mismatch for {name}: expected {expected_version}, found {actual_version or 'missing'}")
    return errors

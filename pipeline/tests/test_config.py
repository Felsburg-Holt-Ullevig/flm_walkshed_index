from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from flm_pipeline.config import ConfigError, SourceConfig, load_config, validate_source_files
from flm_pipeline.runtime import pinned_versions, runtime_errors


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "pipeline" / "config" / "denver-source.example.toml"


def test_example_config_is_strict_and_discovery_only() -> None:
    config = load_config(EXAMPLE)
    assert config.config_version == "prototype-config-1"
    assert config.sources["osm"].expected_sha256 is None
    assert config.sources["osm"].path == ROOT / "data" / "raw" / "colorado-261101.osm.pbf"
    assert config.sources["variables_catalog"].path == ROOT / "data" / "raw" / "variables.json"
    assert config.output_root == ROOT / "data" / "generated" / "prototype"


def test_unknown_configuration_field_is_rejected(tmp_path: Path) -> None:
    text = EXAMPLE.read_text(encoding="utf-8").replace('region_id = "denver-union-source-v1"', 'region_id = "denver-union-source-v1"\nunknown_option = true')
    invalid = tmp_path / "unknown.toml"
    invalid.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown fields: unknown_option"):
        load_config(invalid)


def test_non_nested_bbox_is_rejected(tmp_path: Path) -> None:
    text = EXAMPLE.read_text(encoding="utf-8").replace("core_bbox = [-105.04, 39.72, -104.97, 39.79]", "core_bbox = [-106.0, 39.72, -104.97, 39.79]")
    invalid = tmp_path / "bbox.toml"
    invalid.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="bboxes must be nested"):
        load_config(invalid)


def test_station_outside_extract_bbox_is_rejected(tmp_path: Path) -> None:
    text = EXAMPLE.read_text(encoding="utf-8").replace("station_lonlat = [-105.0006, 39.7530]", "station_lonlat = [-106.0, 39.7530]")
    invalid = tmp_path / "station.toml"
    invalid.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="station_lonlat must be within extract_bbox"):
        load_config(invalid)


def test_unknown_crs_is_rejected(tmp_path: Path) -> None:
    text = EXAMPLE.read_text(encoding="utf-8").replace('storage_crs = "EPSG:4326"', 'storage_crs = "EPSG:99999999"')
    invalid = tmp_path / "crs.toml"
    invalid.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="storage_crs is not a recognized CRS"):
        load_config(invalid)


def test_missing_input_is_reported(tmp_path: Path) -> None:
    config = load_config(EXAMPLE)
    missing = SourceConfig("test", tmp_path / "missing.osm.pbf", "missing.osm.pbf", None)
    changed = replace(config, sources={"missing": missing})
    assert validate_source_files(changed) == ["sources.test is missing: missing.osm.pbf"]


def test_unsupported_python_runtime_is_rejected() -> None:
    errors = runtime_errors("cpython", (3, 13, 0), "Windows", "AMD64")
    assert any("Expected Python 3.12.10 or 3.12.14" in error for error in errors)


def test_unsupported_runtime_implementation_is_rejected() -> None:
    errors = runtime_errors("pypy", (3, 12, 14), "Windows", "AMD64")
    assert any("Expected CPython" in error for error in errors)


def test_lock_files_pin_application_bootstrap_and_package_validator_versions() -> None:
    pins = pinned_versions()
    assert pins["osmium"] == "4.3.2"
    assert pins["pip"] == "26.2.2"
    assert pins["jsonschema"] == "4.25.1"
    assert len(pins) == 29


def test_supported_windows_patch_versions():
    assert runtime_errors("cpython", (3, 12, 10), "Windows", "AMD64") == []
    assert runtime_errors("cpython", (3, 12, 14), "Windows", "AMD64") == []
    assert runtime_errors("cpython", (3, 12, 11), "Windows", "AMD64")

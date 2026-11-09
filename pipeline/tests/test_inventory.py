from __future__ import annotations

import json
from pathlib import Path
import zipfile

import geopandas as gpd
from shapely.geometry import box

from flm_pipeline.config import SourceConfig
from flm_pipeline.inventory import (
    _source_record,
    _scan_census_archive,
    _scan_catalog,
    _zip_shapefile_members,
    _count_values,
    expected_hash_match,
    sha256_file,
)


def _write_census_zip(
    path: Path,
    identifiers: list[str],
    *,
    include_prj: bool = True,
    populations: list[int | float] | None = None,
) -> None:
    frame = gpd.GeoDataFrame(
        {
            "GEOID20": identifiers,
            "POP20": populations if populations is not None else [2] * len(identifiers),
            "HOUSING20": [1] * len(identifiers),
            "geometry": [box(index, 0, index + 1, 1) for index in range(len(identifiers))],
        },
        geometry="geometry",
        crs="EPSG:4269",
    )
    shapefile = path.with_suffix("") / "blocks.shp"
    shapefile.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(shapefile, driver="ESRI Shapefile", engine="pyogrio")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for member in shapefile.parent.iterdir():
            if member.suffix.lower() == ".prj" and not include_prj:
                continue
            archive.write(member, member.name)


def test_census_inventory_counts_rows_and_reports_duplicate_and_malformed_ids(tmp_path: Path) -> None:
    archive = tmp_path / "blocks.zip"
    _write_census_zip(archive, ["000000000000001", "000000000000001", "00000000000000A"])

    result = _scan_census_archive(archive, "census_blocks")

    assert result["actual_feature_count"] == 3
    assert result["identifier_checks"]["duplicate_count"] == 1
    assert result["identifier_checks"]["invalid_format_count"] == 1
    assert result["identifier_checks"]["identifiers_evaluated_as_strings"] is True
    assert not any("not a string field" in message for message in result.get("errors", []))
    assert result["scan"]["complete"] is True
    assert result["scan"]["geometry_validity_checked"] is False


def test_negative_population_is_reported_without_repair(tmp_path: Path) -> None:
    archive = tmp_path / "blocks.zip"
    _write_census_zip(archive, ["000000000000001"], populations=[-1])

    result = _scan_census_archive(archive, "census_blocks")

    assert result["numeric_count_checks"]["POP20"]["negative_count"] == 1
    assert result["numeric_count_checks"]["POP20"]["invalid_count"] == 1
    assert any("Count field POP20" in message for message in result["errors"])


def test_numeric_count_validation_separates_nonfinite_negative_null_and_nonnumeric() -> None:
    state = {"value_count": 0, "null_count": 0, "nonfinite_count": 0, "negative_count": 0, "non_numeric_count": 0}

    _count_values([float("nan"), float("inf"), -1, None, "bad"], state)

    assert state == {
        "value_count": 5,
        "null_count": 1,
        "nonfinite_count": 2,
        "negative_count": 1,
        "non_numeric_count": 1,
    }


def test_missing_shapefile_member_is_reported(tmp_path: Path) -> None:
    archive = tmp_path / "blocks.zip"
    _write_census_zip(archive, ["000000000000001"], include_prj=False)

    integrity, _ = _zip_shapefile_members(archive)

    assert integrity["crc_test"] == "pass"
    assert any(name.lower().endswith(".prj") for name in integrity["missing_required_members"])


def test_zip_crc_corruption_is_reported(tmp_path: Path) -> None:
    archive_path = tmp_path / "blocks.zip"
    _write_census_zip(archive_path, ["000000000000001"])
    with zipfile.ZipFile(archive_path) as archive:
        member = next(item for item in archive.infolist() if item.filename.endswith(".dbf"))
    payload = bytearray(archive_path.read_bytes())
    filename_length = int.from_bytes(payload[member.header_offset + 26 : member.header_offset + 28], "little")
    extra_length = int.from_bytes(payload[member.header_offset + 28 : member.header_offset + 30], "little")
    data_offset = member.header_offset + 30 + filename_length + extra_length
    payload[data_offset] ^= 1
    archive_path.write_bytes(payload)

    integrity, _ = _zip_shapefile_members(archive_path)

    assert integrity["crc_test"] == "fail"
    assert integrity["first_corrupt_member"].endswith(".dbf")


def test_hash_mismatch_does_not_become_a_discovery_match() -> None:
    assert expected_hash_match("a" * 64, None) is None
    assert expected_hash_match("a" * 64, "A" * 64) is True
    assert expected_hash_match("a" * 64, "b" * 64) is False


def test_file_hash_mismatch_fixture_keeps_expected_hash_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "fixture.bin"
    path.write_bytes(b"synthetic source bytes")
    expected = "0" * 64
    source = SourceConfig("fixture", path, "fixture.bin", expected)
    record = _source_record(source)
    record["sha256"] = sha256_file(path)
    record["expected_sha256_matches"] = expected_hash_match(record["sha256"], source.expected_sha256)

    assert record["expected_sha256_matches"] is False
    assert source.expected_sha256 == expected


def test_catalog_inventory_reports_structure_not_observations(tmp_path: Path) -> None:
    path = tmp_path / "variables.json"
    path.write_text(
        json.dumps({"variables": {"GEO_ID": {"label": "Geography"}, "B01003_001E": {"label": "Total population"}}}),
        encoding="utf-8",
    )

    result = _scan_catalog(path)

    assert result["structure"]["variables_entry_count"] == 2
    assert result["selected_field_presence"]["B01003_001E"]["present"] is True
    assert result["acs_observations_retrieved"] is False
    assert result["dataset_vintage_verified"] is False

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

import osmium
import pyogrio
import pytest

from flm_pipeline import cli
from flm_pipeline.code_identity import code_identity
from flm_pipeline.config import load_config
from flm_pipeline.extractor import ExtractionFailure, _coordinates


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = ROOT / "pipeline" / "config" / "denver-source.example.toml"
EARTH_TRIAL_FIXTURES = ROOT / "data" / "staging" / "prototype" / "earth-trials"


def _write_pbf(
    path: Path,
    *,
    nodes: list[tuple[int, tuple[float, float], dict[str, str]]],
    ways: list[tuple[int, list[int], dict[str, str]]],
    relations: list[tuple[int, list[tuple[str, int, str]], dict[str, str]]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with osmium.SimpleWriter(path, overwrite=True) as writer:
        for osm_id, location, tags in nodes:
            writer.add_node(osmium.osm.mutable.Node(id=osm_id, location=location, tags=tags))
        for osm_id, refs, tags in ways:
            writer.add_way(osmium.osm.mutable.Way(id=osm_id, nodes=refs, tags=tags))
        for osm_id, members, tags in relations or []:
            writer.add_relation(osmium.osm.mutable.Relation(id=osm_id, members=members, tags=tags))


def _pbf_counts(path: Path) -> dict[str, int]:
    counts = {"node": 0, "way": 0, "relation": 0}

    class Handler(osmium.SimpleHandler):
        def node(self, _node: Any) -> None:
            counts["node"] += 1

        def way(self, _way: Any) -> None:
            counts["way"] += 1

        def relation(self, _relation: Any) -> None:
            counts["relation"] += 1

    Handler().apply_file(str(path), locations=False)
    return counts


def _safe_pbf_counts(path: Path) -> dict[str, int]:
    try:
        return _pbf_counts(path)
    except Exception:
        return {"node": 0, "way": 0, "relation": 0}


def _prepare_inputs(
    tmp_path: Path,
    pbf: Path,
    *,
    expected_hash: str | None = None,
    entity_counts: dict[str, int] | None = None,
) -> tuple[Path, Path, Path]:
    relative_pbf = pbf.relative_to(ROOT).as_posix()
    config_text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    config_text = config_text.replace('path = "data/raw/colorado-261101.osm.pbf"', f'path = "{relative_pbf}"')
    config_text = config_text.replace("core_bbox = [-105.04, 39.72, -104.97, 39.79]", "core_bbox = [0.5, 0.5, 1.5, 1.5]")
    config_text = config_text.replace("extract_bbox = [-105.08, 39.68, -104.93, 39.83]", "extract_bbox = [0.0, 0.0, 2.0, 2.0]")
    config_text = config_text.replace("expanded_bbox = [-105.12, 39.64, -104.89, 39.87]", "expanded_bbox = [-1.0, -1.0, 3.0, 3.0]")
    config_text = config_text.replace("station_lonlat = [-105.0006, 39.7530]", "station_lonlat = [1.0, 1.0]")
    source_hash = hashlib.sha256(pbf.read_bytes()).hexdigest()
    expected_hash = expected_hash if expected_hash is not None else source_hash
    config_text = config_text.replace('expected_sha256 = ""', f'expected_sha256 = "{expected_hash}"', 1)
    config_path = tmp_path / "extract-config.toml"
    config_path.write_text(config_text, encoding="utf-8", newline="\n")
    config = load_config(config_path)
    inventory_path = tmp_path / "source-inventory.json"
    identity = code_identity()
    inventory = {
        "inventory_version": "source-inventory-1",
        "created_at_utc": "2026-11-02T00:00:00+00:00",
        "code_identity": identity,
        "region_id": config.region_id,
        "configuration": config_path.relative_to(ROOT).as_posix(),
        "inventory_status": "pass",
        "sources": {
            "osm": {
                "source_id": "osm",
                "path": relative_pbf,
                "expected_sha256": expected_hash,
                "sha256": source_hash,
                "expected_sha256_matches": source_hash.casefold() == expected_hash.casefold(),
                "file_stable_during_inventory": True,
                "validation_status": "pass",
                "scan": {"complete": True, "sampled": False},
                "entity_counts": entity_counts if entity_counts is not None else _safe_pbf_counts(pbf),
            }
        },
        "limitations": [],
    }
    inventory_bytes = (json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    inventory_path.write_bytes(inventory_bytes)
    inventory_hash = hashlib.sha256(inventory_bytes).hexdigest()
    report_path = tmp_path / "inventory-run-report.json"
    run_report = {
        "report_version": "prototype-run-1",
        "status": "pass",
        "inventory_status": "pass",
        "source_inventory_sha256": inventory_hash,
        "code_identity": identity,
        "configuration": {"path": config_path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()},
    }
    report_path.write_text(json.dumps(run_report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return config_path, inventory_path, report_path


def _invoke_extract(config_path: Path, inventory_path: Path, report_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code = cli.main(
        [
            "extract",
            "--config",
            str(config_path),
            "--source-inventory",
            str(inventory_path),
            "--inventory-report",
            str(report_path),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    return code, output


def _invoke_export(config_path: Path, extraction_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code = cli.main(["export", "--config", str(config_path), "--extraction", str(extraction_path)])
    output = json.loads(capsys.readouterr().out)
    return code, output


def _invoke_earth_export(config_path: Path, extraction_path: Path, gpkg_export_path: Path, capsys: pytest.CaptureFixture[str], review_profile: str = "topology") -> tuple[int, dict[str, Any]]:
    code = cli.main(["earth-export", "--config", str(config_path), "--extraction", str(extraction_path), "--gpkg-export", str(gpkg_export_path), "--dataset-kind", "synthetic", "--review-profile", review_profile])
    output = json.loads(capsys.readouterr().out)
    return code, output


def _kmz_semantics(path: Path) -> dict[str, list[tuple[str, tuple[tuple[str, str], ...], tuple[str, ...]]]]:
    import zipfile
    import xml.etree.ElementTree as ET

    ns = {"k": "http://www.opengis.net/kml/2.2"}
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("doc.kml"))
    result: dict[str, list[tuple[str, tuple[tuple[str, str], ...], tuple[str, ...]]]] = {}
    for folder in root.findall(".//k:Folder", ns):
        name = folder.findtext("k:name", namespaces=ns) or ""
        if name == "Package information":
            continue
        values = []
        for placemark in folder.findall("k:Placemark", ns):
            fields = tuple(sorted((data.get("name", ""), data.findtext("k:value", namespaces=ns) or "") for data in placemark.findall("k:ExtendedData/k:Data", ns) if data.get("name") != "package_id"))
            geometry = tuple(node.text or "" for node in placemark.findall(".//k:coordinates", ns))
            values.append((placemark.findtext("k:name", namespaces=ns) or "", fields, geometry))
        result[name] = sorted(values)
    return result


def _network_pbf(path: Path) -> None:
    _write_pbf(
        path,
        nodes=[
            (1, (0.5, 0.5), {"barrier": "gate"}),
            (2, (1.5, 0.5), {}),
            (3, (-1.0, 0.5), {}),
            (4, (3.0, 0.5), {}),
            (5, (1.0, 1.0), {}),
            (6, (1.5, 1.5), {"crossing": "unmarked"}),
            (7, (1.5, 1.5), {}),
            (8, (1.75, 1.75), {}),
            (9, (0.0, 2.0), {}),
            (10, (3.0, 2.0), {}),
            (11, (-1.0, 1.0), {}),
            (12, (3.0, 1.0), {}),
            (13, (2.5, 1.5), {}),
            (9007199254740993, (0.25, 0.25), {"name": "large-id"}),
        ],
        ways=[
            (10, [3, 1, 2, 4], {"highway": "", "access:conditional": "no @ (night)", "unknown:raw": "Keep Case"}),
            (11, [1, 5], {"highway": "footway", "sidewalk:left": "separate"}),
            (12, [7, 2], {"highway": "path", "bridge": "yes", "layer": "1"}),
            (13, [1, 1, 2, 3, 1], {"highway": "service"}),
            (14, [11, 12], {"highway": "primary"}),
            (15, [9, 10], {"highway": "service"}),
            (17, [6, 13], {"highway": "footway", "bridge": "yes", "layer": "1", "custom:key": "", "note": "Unicode café & <trail> \"quotes\" ]]>"}),
        ],
        relations=[
            (20, [("w", 10, "route"), ("n", 888, "stop"), ("w", 999, "outside"), ("r", 21, "child")], {"type": "route", "note": "raw"}),
            (21, [("w", 10, "outer")], {"type": "multipolygon"}),
            (22, [("r", 20, "only-relation-member")], {"type": "route"}),
        ],
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_cli_extracts_complete_ways_and_preserves_source_identity_deterministically(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pbf = tmp_path / "synthetic-network.osm.pbf"
    _network_pbf(pbf)
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf)

    code1, result1 = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)
    code2, result2 = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)

    assert code1 == code2 == 0
    assert result1["status"] == result2["status"] == "pass"
    output1 = ROOT / result1["output_directory"]
    output2 = ROOT / result2["output_directory"]
    for filename in ("nodes.jsonl", "ways.jsonl", "relations.jsonl"):
        assert (output1 / filename).read_bytes() == (output2 / filename).read_bytes()
    nodes = _read_jsonl(output1 / "nodes.jsonl")
    ways = _read_jsonl(output1 / "ways.jsonl")
    relations = _read_jsonl(output1 / "relations.jsonl")
    nodes_by_id = {node["osm_id"]: node for node in nodes}
    ways_by_id = {way["osm_id"]: way for way in ways}
    relations_by_id = {relation["osm_id"]: relation for relation in relations}

    assert {"10", "11", "12", "13", "15", "17"} == set(ways_by_id)
    assert ways_by_id["10"]["node_refs"] == ["3", "1", "2", "4"]
    assert ways_by_id["10"]["tags"] == {"highway": "", "access:conditional": "no @ (night)", "unknown:raw": "Keep Case"}
    assert ways_by_id["13"]["node_refs"] == ["1", "1", "2", "3", "1"]
    assert {"1", "2", "3", "4", "5", "6", "7", "9", "10", "13", "9007199254740993"} <= set(nodes_by_id)
    assert "8" not in nodes_by_id
    assert nodes_by_id["6"]["lon"] == nodes_by_id["7"]["lon"]
    assert "6" != "7"
    assert "6" in ways_by_id["17"]["node_refs"] and "7" in ways_by_id["12"]["node_refs"]
    assert set(relations_by_id) == {"20", "21"}
    relation20 = relations_by_id["20"]["members"]
    assert relation20 == [
        {"type": "way", "ref": "10", "role": "route", "resolved": True},
        {"type": "node", "ref": "888", "role": "stop", "resolved": False},
        {"type": "way", "ref": "999", "role": "outside", "resolved": False},
        {"type": "relation", "ref": "21", "role": "child", "resolved": True},
    ]
    run_report = json.loads((output1 / "run-report.json").read_text(encoding="utf-8"))
    assert run_report["checks"]["required_way_references_resolve"] is True
    assert result1["output_hashes"]["ways.jsonl"] == result2["output_hashes"]["ways.jsonl"]


def test_cli_reports_empty_selection_without_claiming_a_routing_network(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pbf = tmp_path / "empty-network.osm.pbf"
    _write_pbf(
        pbf,
        nodes=[(1, (0.5, 0.5), {"barrier": "gate"}), (2, (-1.0, 1.0), {}), (3, (3.0, 1.0), {})],
        ways=[(10, [2, 3], {"highway": "primary"})],
    )
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf)

    code, result = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)

    assert code == 0
    assert result["status"] == "empty"
    output = ROOT / result["output_directory"]
    assert [node["osm_id"] for node in _read_jsonl(output / "nodes.jsonl")] == ["1"]
    assert _read_jsonl(output / "ways.jsonl") == []
    metadata = json.loads((output / "extraction.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "empty"
    assert metadata["counts"]["selected_ways"] == 0


@pytest.mark.parametrize(
    ("case", "expected_diagnostic"),
    [
        ("missing-reference", "absent from source"),
        ("duplicate-node", "duplicate entity identity"),
        ("duplicate-way", "duplicate entity identity"),
        ("duplicate-relation", "duplicate entity identity"),
        ("short-way", "fewer than two node references"),
        ("malformed-pbf", "PBF node_index pass failed"),
    ],
)
def test_failures_remain_in_staging_and_never_promote(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
    expected_diagnostic: str,
) -> None:
    pbf = tmp_path / f"{case}.osm.pbf"
    if case == "missing-reference":
        _write_pbf(pbf, nodes=[(1, (0.5, 0.5), {})], ways=[(10, [1, 999], {"highway": "path"})])
    elif case == "duplicate-node":
        _write_pbf(pbf, nodes=[(1, (0.5, 0.5), {}), (1, (0.6, 0.6), {})], ways=[])
    elif case == "duplicate-way":
        _write_pbf(pbf, nodes=[], ways=[(10, [1, 2], {"highway": "path"}), (10, [3, 4], {"highway": "service"})])
    elif case == "duplicate-relation":
        _write_pbf(pbf, nodes=[], ways=[], relations=[(20, [], {}), (20, [], {})])
    elif case == "short-way":
        _write_pbf(pbf, nodes=[(1, (0.5, 0.5), {})], ways=[(10, [1], {"highway": "path"})])
    else:
        pbf.write_bytes(b"not a valid PBF")
    counts = {"node": 0, "way": 0, "relation": 0} if case == "malformed-pbf" else None
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf, entity_counts=counts)

    code, result = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)

    assert code == 1
    assert result["status"] == "fail"
    report_path = ROOT / result["run_report"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert expected_diagnostic in str(report["diagnostics"])
    assert not (load_config(config_path).output_root / result["run_id"]).exists()


def test_unpinned_source_hash_is_rejected_before_creating_a_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pbf = tmp_path / "unpinned.osm.pbf"
    _write_pbf(pbf, nodes=[], ways=[])
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf, expected_hash="")

    code, result = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)

    assert code == 1
    assert result["status"] == "fail"
    assert result["phase"] == "preflight"
    assert "expected_sha256 to be pinned" in result["errors"][0]
    assert "run_id" not in result


def test_mismatched_source_hash_is_rejected_before_processing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pbf = tmp_path / "mismatched.osm.pbf"
    _write_pbf(pbf, nodes=[], ways=[])
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf, expected_hash="0" * 64)

    code, result = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)

    assert code == 1
    assert result["status"] == "fail"
    assert "does not match sources.osm.expected_sha256" in result["errors"][0]


def test_inventory_hash_mismatch_is_rejected_before_processing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pbf = tmp_path / "inventory-mismatch.osm.pbf"
    _write_pbf(pbf, nodes=[], ways=[])
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf)
    report = json.loads(inventory_report_path.read_text(encoding="utf-8"))
    report["source_inventory_sha256"] = "0" * 64
    inventory_report_path.write_text(json.dumps(report), encoding="utf-8", newline="\n")

    code, result = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)

    assert code == 1
    assert result["status"] == "fail"
    assert "does not match the source inventory file hash" in result["errors"][0]


def test_failed_atomic_promotion_keeps_candidate_in_staging(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    pbf = tmp_path / "promotion-failure.osm.pbf"
    # The second reference is deliberately absent; use a complete source so only promotion fails.
    _write_pbf(pbf, nodes=[(1, (0.5, 0.5), {}), (2, (0.6, 0.6), {})], ways=[(10, [1, 2], {"highway": "path"})])
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf)
    original_replace = cli.os.replace

    def fail_candidate_move(source: str | Path, destination: str | Path) -> None:
        if Path(source).name == "candidate" and Path(destination).parent.name == "prototype":
            raise OSError("synthetic promotion failure")
        original_replace(source, destination)

    monkeypatch.setattr(cli.os, "replace", fail_candidate_move)
    code, result = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)

    assert code == 1
    assert result["status"] == "fail"
    assert "Promotion failed: synthetic promotion failure" in result["diagnostics"][-1]
    assert not (load_config(config_path).output_root / result["run_id"]).exists()
    assert (ROOT / result["run_report"]).is_file()


def test_supervisor_failure_overrides_worker_success_and_never_promotes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pbf = tmp_path / "interrupted.osm.pbf"
    _write_pbf(pbf, nodes=[(1, (0.5, 0.5), {}), (2, (0.6, 0.6), {})], ways=[(10, [1, 2], {"highway": "path"})])
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf)

    def timed_out_worker(command: list[str], *_args: Any) -> dict[str, Any]:
        result_path = Path(command[command.index("--result") + 1])
        result_path.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
        return {
            "exit_code": -9,
            "duration_seconds": 1,
            "sampled_peak_rss_bytes": 1024,
            "sample_interval_seconds": 1,
            "rss_limit_bytes": 4 * 1024**3,
            "failure_reason": "stage exceeded 1 seconds",
            "child_cleanup_complete": True,
            "remaining_process_ids": [],
            "log": "extract-worker.log",
        }

    monkeypatch.setattr(cli, "_supervise", timed_out_worker)
    code, result = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)

    assert code == 1
    assert result["status"] == "fail"
    report = json.loads((ROOT / result["run_report"]).read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    assert any("stage exceeded" in str(item) for item in report["diagnostics"])
    assert not (load_config(config_path).output_root / result["run_id"]).exists()


def test_invalid_coordinate_is_rejected_with_entity_diagnostic() -> None:
    class InvalidLocation:
        @staticmethod
        def valid() -> bool:
            return False

    class Node:
        location = InvalidLocation()

    with pytest.raises(ExtractionFailure, match="Invalid coordinates for node 9007199254740993") as error:
        _coordinates(Node(), "9007199254740993", "synthetic-test")
    assert error.value.diagnostics[0]["osm_id"] == "9007199254740993"


def test_cli_exports_source_network_layers_and_reconciles_ordered_segments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pbf = tmp_path / "gpkg-network.osm.pbf"
    _write_pbf(
        pbf,
        nodes=[
            (1, (0.5, 0.5), {"barrier": "gate"}),
            (2, (0.5, 0.5), {"note": "same coordinates, distinct identity"}),
            (3, (1.5, 1.5), {}),
            (4, (3.0, 1.0), {}),
            (5, (1.0, 1.0), {"crossing": "unmarked"}),
        ],
        ways=[
            (10, [1, 2, 3], {"highway": "footway", "unknown:raw": "Keep Case"}),
            (11, [2, 1, 3], {"highway": "path"}),
            (12, [3, 4], {"highway": "service"}),
            (13, [1, 1, 3], {"highway": "steps"}),
        ],
        relations=[(20, [("w", 10, "route"), ("n", 999, "unresolved")], {"type": "route"})],
    )
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf)
    extract_code, extraction = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)
    assert extract_code == 0
    extraction_path = ROOT / extraction["output_directory"]

    export_code, exported = _invoke_export(config_path, extraction_path, capsys)
    second_code, second_export = _invoke_export(config_path, extraction_path, capsys)

    assert export_code == second_code == 0, (exported, second_export)
    assert exported["status"] == second_export["status"] == "pass_with_warnings"
    assert exported["semantic_layer_sha256"] == second_export["semantic_layer_sha256"]
    gpkg = ROOT / exported["source_network_gpkg"]
    assert {row[0] for row in pyogrio.list_layers(gpkg).tolist()} == {
        "source_nodes", "source_ways", "source_segments", "source_relations", "coverage"
    }
    nodes = pyogrio.read_dataframe(gpkg, layer="source_nodes")
    ways = pyogrio.read_dataframe(gpkg, layer="source_ways")
    segments = pyogrio.read_dataframe(gpkg, layer="source_segments")
    relations = pyogrio.read_dataframe(gpkg, layer="source_relations", read_geometry=False)
    coverage = pyogrio.read_dataframe(gpkg, layer="coverage")

    assert all(isinstance(value, str) for value in nodes["osm_id"])
    assert set(nodes.loc[nodes["lon"] == 0.5, "osm_id"]) == {"1", "2"}
    assert nodes.loc[nodes["osm_id"] == "5", "inside_core"].iloc[0] == 1
    assert ways.loc[ways["osm_id"] == "12", "geometry"].iloc[0].coords[-1] == (3.0, 1.0)
    way10 = ways.loc[ways["osm_id"] == "10"].iloc[0]
    assert way10["node_refs_json"] == '["1","2","3"]'
    assert json.loads(way10["tags_json"]) == {"highway": "footway", "unknown:raw": "Keep Case"}
    assert len(segments) == 7
    first_segment = segments.loc[segments["segment_id"] == "way/10/segment/0"].iloc[0]
    assert (first_segment["from_node_id"], first_segment["to_node_id"], first_segment["sequence"]) == ("1", "2", 0)
    assert first_segment["length_geodesic_m"] == 0.0 and first_segment["zero_length"] == 1
    assert len(relations) == 1 and relations.loc[0, "osm_id"] == "20"
    assert len(coverage) == 3 and coverage.crs.to_epsg() == 4326
    assert exported["counts"]["source_nodes"] == 5
    assert exported["counts"]["source_ways"] == 4
    assert exported["worker"]["sampled_peak_rss_bytes"] > 0
    assert exported["worker"]["child_cleanup_complete"] is True
    assert exported["counts"]["source_segments"] == 7
    assert exported["diagnostics"]["repeated_way_node_reference_count"] == 1
    assert exported["diagnostics"]["zero_length_segment_count"] == 3
    assert exported["diagnostics"]["duplicate_geometries"]["source_ways"]["duplicate_feature_count"] == 2
    assert exported["diagnostics"]["duplicate_geometries"]["source_segments"]["duplicate_feature_count"] == 4
    report = json.loads((ROOT / exported["run_report"]).read_text(encoding="utf-8"))
    assert all(report["checks"].values())
    assert report["storage_crs"] == "EPSG:4326"
    assert report["inspection_crs"] == "EPSG:26913"


def test_cli_export_preserves_disconnected_crossings_and_shared_source_junctions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Source identity, including grade separation, survives both adapters."""
    pbf = tmp_path / "topology-review.osm.pbf"
    _write_pbf(
        pbf,
        nodes=[
            (1, (0.5, 1.0), {}),
            (2, (1.0, 1.0), {"crossing": "uncontrolled"}),
            (3, (1.5, 1.0), {}),
            (4, (1.0, 1.0), {}),
            (5, (1.0, 1.5), {}),
            (6, (0.75, 0.5), {}),
            (7, (0.75, 1.5), {}),
            (8, (3.0, 1.0), {}),
            (9, (0.25, 0.25), {"barrier": "gate", "foot": "private"}),
            (10, (1.5, 0.5), {}),
            (11, (1.5, 1.5), {}),
            (12, (0.25, 1.75), {"barrier": "bollard"}),
        ],
        ways=[
            (10, [1, 2, 3, 8], {"highway": "residential", "sidewalk": "both"}),
            (11, [4, 5], {"highway": "footway", "bridge": "yes", "layer": "1"}),
            (12, [6, 7], {"highway": "path"}),
            (13, [10, 11], {"highway": "service", "tunnel": "yes", "layer": "-1"}),
            (14, [2, 9], {"highway": "footway", "footway": "crossing"}),
        ],
    )
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf)
    extract_code, extraction = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)
    assert extract_code == 0, extraction
    export_code, exported = _invoke_export(config_path, ROOT / extraction["output_directory"], capsys)
    assert export_code == 0 and exported["status"] == "pass", exported
    gpkg = ROOT / exported["source_network_gpkg"]
    nodes = pyogrio.read_dataframe(gpkg, layer="source_nodes").set_index("osm_id")
    segments = pyogrio.read_dataframe(gpkg, layer="source_segments").set_index("segment_id")
    ways = pyogrio.read_dataframe(gpkg, layer="source_ways").set_index("osm_id")
    # These pairs are specified independently of extraction/export implementation.
    expected = {
        "way/10/segment/0": ("1", "2"),
        "way/10/segment/1": ("2", "3"),
        "way/10/segment/2": ("3", "8"),
        "way/11/segment/0": ("4", "5"),
        "way/12/segment/0": ("6", "7"),
        "way/13/segment/0": ("10", "11"),
        "way/14/segment/0": ("2", "9"),
    }
    actual = {key: (row.from_node_id, row.to_node_id) for key, row in segments.iterrows()}
    assert actual == expected
    assert set(nodes.index) == {str(value) for value in range(1, 13)}
    assert nodes.loc["2"].geometry.equals_exact(nodes.loc["4"].geometry, 0)
    adjacency: dict[str, set[str]] = {key: set() for key in nodes.index}
    for start, end in actual.values():
        adjacency[start].add(end)
        adjacency[end].add(start)
    pending = set(adjacency)
    components = set()
    while pending:
        reached, frontier = set(), {next(iter(pending))}
        while frontier:
            reached.update(frontier)
            frontier = {neighbor for key in frontier for neighbor in adjacency[key]} - reached
        pending.difference_update(reached)
        components.add(frozenset(reached))
    assert components == {
        frozenset({"1", "2", "3", "8", "9"}),
        frozenset({"4", "5"}),
        frozenset({"6", "7"}),
        frozenset({"10", "11"}),
        frozenset({"12"}),
    }
    assert segments.loc["way/10/segment/0"].geometry.intersects(segments.loc["way/12/segment/0"].geometry)
    assert segments.loc["way/10/segment/1"].geometry.intersects(segments.loc["way/13/segment/0"].geometry)
    assert json.loads(ways.loc["11", "tags_json"])["bridge"] == "yes"
    assert json.loads(ways.loc["13", "tags_json"])["tunnel"] == "yes"
    assert json.loads(nodes.loc["9", "tags_json"]) == {"barrier": "gate", "foot": "private"}
    assert nodes.loc["8", "inside_extract"] == 0
    assert list(ways.loc["10"].geometry.coords)[-1] == (3.0, 1.0)
    assert exported["counts"]["source_nodes"] == 12
    assert exported["counts"]["source_ways"] == 5
    assert exported["counts"]["source_segments"] == 7


def test_cli_earth_export_preserves_topology_ids_tags_and_review_instructions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_dir = EARTH_TRIAL_FIXTURES / "topology"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    pbf = fixture_dir / "earth-topology.osm.pbf"
    _write_pbf(
        pbf,
        nodes=[
            (1, (0.5, 1.0), {}), (2, (1.0, 1.0), {"crossing": "uncontrolled"}),
            (3, (1.5, 1.0), {}), (4, (1.0, 1.0), {}), (5, (1.0, 1.5), {}),
            (6, (0.75, 0.5), {}), (7, (0.75, 1.5), {}), (8, (3.0, 1.0), {}),
            (9, (0.25, 0.25), {"barrier": "gate", "foot": "private"}),
            (10, (1.5, 0.5), {}), (11, (1.5, 1.5), {}), (12, (0.25, 1.75), {"barrier": "bollard"}),
        ],
        ways=[
            (10, [1, 2, 3, 8], {"highway": "residential", "sidewalk": "both"}),
            (11, [4, 5], {"highway": "footway", "bridge": "yes", "layer": "1"}),
            (12, [6, 7], {"highway": "path"}),
            (13, [10, 11], {"highway": "service", "tunnel": "yes", "layer": "-1"}),
            (14, [2, 9], {"highway": "footway", "footway": "crossing"}),
        ],
    )
    config, inventory, inventory_report = _prepare_inputs(fixture_dir, pbf)
    extract_code, extracted = _invoke_extract(config, inventory, inventory_report, capsys)
    assert extract_code == 0, extracted
    extraction_path = ROOT / extracted["output_directory"]
    gpkg_code, exported = _invoke_export(config, extraction_path, capsys)
    assert gpkg_code == 0, exported
    gpkg_export_path = ROOT / exported["run_report"]
    gpkg_export_path = gpkg_export_path.parent
    earth_code, package = _invoke_earth_export(config, extraction_path, gpkg_export_path, capsys)
    assert earth_code == 0 and package["status"] == "pass", package
    package_dir = ROOT / package["output_directory"]
    assert package["counts"]["source_nodes"] == 12
    assert package["counts"]["source_ways"] == 5
    assert package["counts"]["source_segments"] == 7
    assert package["counts"]["source_evidence_records"] == 24
    assert (package_dir / "review-cases.csv").is_file()
    assert (package_dir / "review-observations-template.csv").is_file()
    evidence = [json.loads(line) for line in (package_dir / "source-evidence.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(record.get("entity_type") == "node" and record["osm_id"] == "4" for record in evidence)
    assert any(record.get("entity_type") == "segment" and record["segment_id"] == "way/10/segment/1" and record["from_node_id"] == "2" for record in evidence)
    import zipfile
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(ROOT / package["kmz"]) as archive:
        assert set(archive.namelist()) == {"doc.kml", "icons/source-node.png", "icons/review-case.png", "icons/diagnostic.png"}
        root = ET.fromstring(archive.read("doc.kml"))
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    assert len(root.findall(".//k:Placemark", ns)) == package["counts"]["package_placemark_count"]
    names = {node.text for node in root.findall(".//k:Folder/k:name", ns)}
    assert {"Package information", "Review cases", "Coverage", "Source nodes", "Source segments", "Source ways", "Diagnostics"} <= names
    kml = (ET.tostring(root, encoding="unicode"))
    assert "bridge" in kml or "tunnel" in kml
    segment = next(item for item in root.findall(".//k:Placemark", ns) if item.findtext("k:name", namespaces=ns) == "way/10/segment/0")
    import html
    balloon = html.unescape(segment.findtext("k:description", namespaces=ns))
    assert balloon.index("From node") < balloon.index("Technical details")
    assert balloon.index("Length along Earth's surface") < balloon.index("Package ID")
    assert "Road/path type" in balloon and "residential" in balloon
    assert segment.findtext("k:Style/k:BalloonStyle/k:text", namespaces=ns) == "$[description]"

    assert "way/10/segment/1" in kml and "way/13/segment/0" in kml
    assert "source_ids" in kml and "node/2" in kml and "node/4" in kml
    assert "icons/source-node.png" in kml and "icons/review-case.png" in kml and "icons/diagnostic.png" in kml
    assert "google_earth_import" in json.loads((package_dir / "inspection-manifest.json").read_text(encoding="utf-8"))["manual_viewer_checks"]
    assert "does not establish a source-node connection" in (package_dir / "README.md").read_text(encoding="utf-8") or "visual line crossings" in (package_dir / "README.md").read_text(encoding="utf-8")
    report = json.loads((package_dir / "run-report.json").read_text(encoding="utf-8"))
    assert report["worker"]["exit_code"] == 0
    assert report["worker"]["sampled_peak_rss_bytes"] > 0
    assert report["manual_viewer_checks"]["google_earth_import"] == "not_run"

    repeat_code, repeat_package = _invoke_earth_export(config, extraction_path, gpkg_export_path, capsys)
    assert repeat_code == 0 and repeat_package["status"] == "pass"
    repeat_dir = ROOT / repeat_package["output_directory"]
    repeat_manifest = json.loads((repeat_dir / "inspection-manifest.json").read_text(encoding="utf-8"))
    manifest = json.loads((package_dir / "inspection-manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_evidence_semantic_sha256"] == repeat_manifest["source_evidence_semantic_sha256"]
    assert _kmz_semantics(ROOT / package["kmz"]) == _kmz_semantics(ROOT / repeat_package["kmz"])

    from flm_pipeline import kml_export

    for name, message in (("MAX_PLACEMARKS", "exceeds first-trial limits"), ("MAX_VERTICES", "exceeds first-trial limits"), ("MAX_PAYLOAD_BYTES", "exceeds trial byte limit")):
        candidate = tmp_path / f"limited-{name.lower()}"
        original_limit = getattr(kml_export, name)
        monkeypatch.setattr(kml_export, name, 1)
        with pytest.raises(kml_export.InspectionFailure, match=message):
            kml_export._build_candidate(config, extraction_path, gpkg_export_path, candidate, "limit-trial", "synthetic", "topology")
        assert not (candidate / "run-report.json").exists()
        monkeypatch.setattr(kml_export, name, original_limit)

    corrupted = tmp_path / "corrupted-package"
    shutil.copytree(package_dir, corrupted)
    with (corrupted / "review-cases.csv").open("a", encoding="utf-8") as stream:
        stream.write("changed\n")
    with pytest.raises(kml_export.InspectionFailure, match="does not match its manifest"):
        kml_export._validate_candidate(corrupted, package["package_id"])

    original_supervise = cli._supervise

    def timeout_supervisor(*_args: Any, **_kwargs: Any) -> dict[str, object]:
        return {"exit_code": -9, "failure_reason": "timeout", "duration_seconds": 1.0, "sampled_peak_rss_bytes": 0, "sample_interval_seconds": 1, "child_cleanup_complete": True}

    before = {path.name for path in load_config(config).output_root.iterdir() if path.is_dir()}
    monkeypatch.setattr(cli, "_supervise", timeout_supervisor)
    from flm_pipeline.kml_export import export_inspection_package

    timeout_code, timeout_result = export_inspection_package(config, extraction_path, gpkg_export_path, "synthetic", "topology")
    assert timeout_code == 1 and timeout_result["status"] == "fail"
    assert timeout_result["stage_directory"] is not None
    assert json.loads((ROOT / timeout_result["stage_directory"] / "run-report.json").read_text(encoding="utf-8"))["status"] == "fail"
    assert {path.name for path in load_config(config).output_root.iterdir() if path.is_dir()} == before

    def build_then_fail_promotion(command: list[str], *_args: Any, **_kwargs: Any) -> dict[str, object]:
        options = {command[index]: command[index + 1] for index in range(len(command) - 1) if command[index].startswith("--")}
        code = kml_export.build_worker(Path(options["--config"]), Path(options["--extraction"]), Path(options["--gpkg-export"]), Path(options["--candidate"]), Path(options["--result"]), options["--package-id"], options["--dataset-kind"], options["--review-profile"])
        return {"exit_code": code, "failure_reason": None, "duration_seconds": 1.0, "sampled_peak_rss_bytes": 1, "sample_interval_seconds": 1, "child_cleanup_complete": True}

    def fail_promotion(_source: Path, _destination: Path) -> None:
        raise OSError("simulated promotion failure")

    monkeypatch.setattr(cli, "_supervise", build_then_fail_promotion)
    monkeypatch.setattr(kml_export, "_promote_directory", fail_promotion)
    promotion_code, promotion_result = export_inspection_package(config, extraction_path, gpkg_export_path, "synthetic", "topology")
    assert promotion_code == 1 and promotion_result["status"] == "fail"
    assert "simulated promotion failure" in promotion_result["errors"][0]
    assert {path.name for path in load_config(config).output_root.iterdir() if path.is_dir()} == before
    monkeypatch.setattr(cli, "_supervise", original_supervise)


def test_cli_earth_export_retains_large_ids_raw_tags_and_diagnostic_examples(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture_dir = EARTH_TRIAL_FIXTURES / "diagnostic"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    pbf = fixture_dir / "earth-diagnostics.osm.pbf"
    _network_pbf(pbf)
    config, inventory, inventory_report = _prepare_inputs(fixture_dir, pbf)
    extract_code, extracted = _invoke_extract(config, inventory, inventory_report, capsys)
    assert extract_code == 0, extracted
    extraction_path = ROOT / extracted["output_directory"]
    gpkg_code, exported = _invoke_export(config, extraction_path, capsys)
    assert gpkg_code == 0, exported
    earth_code, package = _invoke_earth_export(config, extraction_path, ROOT / Path(exported["run_report"]).parent, capsys, "diagnostic")
    assert earth_code == 0 and package["status"] == "pass", package
    package_dir = ROOT / package["output_directory"]
    assert package["counts"]["source_relations"] == 2
    assert package["counts"]["source_evidence_records"] == package["counts"]["source_nodes"] + package["counts"]["source_ways"] + package["counts"]["source_relations"] + package["counts"]["source_segments"]
    evidence_text = (package_dir / "source-evidence.jsonl").read_text(encoding="utf-8")
    assert '"osm_id":"9007199254740993"' in evidence_text
    assert '"custom:key":""' in evidence_text
    assert package["counts"]["package_placemark_count"] > package["counts"]["source_nodes"]
    assert package["review_profile"] == "diagnostic"
    assert package["counts"]["diagnostic_markers"] > 0
    assert {"zero_length_segment", "repeated_way_node_reference", "duplicate_geometry", "unresolved_relation_member"} <= set(package["counts"]["diagnostic_marker_counts"])
    cases = (package_dir / "review-cases.csv").read_text(encoding="utf-8-sig")
    assert "DIAG-01" in cases and "DIAG-04" in cases and "relation/20 member/1 ref/888" in cases
    manifest = json.loads((package_dir / "inspection-manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert all(manifest["checks"].values())

    report_path = ROOT / exported["run_report"]
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    report_data["output"]["sha256"] = "0" * 64
    report_path.write_text(json.dumps(report_data, indent=2) + "\n", encoding="utf-8")
    rejected_code, rejected = _invoke_earth_export(config, extraction_path, report_path.parent, capsys, "diagnostic")
    assert rejected_code == 1 and rejected["status"] == "fail"
    assert "GeoPackage bytes do not match" in rejected["errors"][0] or "Supervised worker failed" in rejected["errors"][0]


def test_cli_exports_empty_extraction_as_explicit_empty_not_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pbf = tmp_path / "empty-gpkg-network.osm.pbf"
    _write_pbf(pbf, nodes=[(1, (0.5, 0.5), {"barrier": "gate"})], ways=[])
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf)
    extract_code, extraction = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)
    assert extract_code == 0 and extraction["status"] == "empty"

    export_code, exported = _invoke_export(config_path, ROOT / extraction["output_directory"], capsys)

    assert export_code == 0 and exported["status"] == "empty", exported
    gpkg = ROOT / exported["source_network_gpkg"]
    assert len(pyogrio.read_dataframe(gpkg, layer="source_nodes")) == 1
    assert len(pyogrio.read_dataframe(gpkg, layer="source_ways")) == 0
    assert len(pyogrio.read_dataframe(gpkg, layer="source_segments")) == 0
    assert exported["counts"]["source_segments"] == 0
    earth_code, package = _invoke_earth_export(config_path, ROOT / extraction["output_directory"], ROOT / Path(exported["run_report"]).parent, capsys)
    assert earth_code == 0 and package["status"] == "empty", package
    manifest = json.loads((ROOT / package["manifest"]).read_text(encoding="utf-8"))
    assert manifest["counts"]["source_ways"] == manifest["counts"]["source_segments"] == 0
    assert "contains no network ways" in (ROOT / package["output_directory"] / "README.md").read_text(encoding="utf-8")


def test_cli_export_rejects_mutated_canonical_input_before_promotion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pbf = tmp_path / "mutated-gpkg-network.osm.pbf"
    _write_pbf(pbf, nodes=[(1, (0.5, 0.5), {}), (2, (1.5, 1.5), {})], ways=[(10, [1, 2], {"highway": "path"})])
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf)
    extract_code, extraction = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)
    assert extract_code == 0
    extraction_path = ROOT / extraction["output_directory"]
    with (extraction_path / "ways.jsonl").open("ab") as stream:
        stream.write(b"{}\n")

    export_code, exported = _invoke_export(config_path, extraction_path, capsys)

    assert export_code == 1 and exported["status"] == "fail"
    assert exported["phase"] == "preflight"
    assert "hash does not match metadata" in exported["errors"][0]

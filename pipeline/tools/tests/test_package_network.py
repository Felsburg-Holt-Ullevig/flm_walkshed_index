"""Focused checks for the release validator and deterministic identity."""
import json
from pathlib import Path
import shutil
import sys
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "pipeline/tools"))
import package_network as package
from package_contract_semantics import graph_digest


def test_all_shared_schemas_pass_draft_2020_12_meta_schema():
    assert set(package.validate_schema_files()) == {"common", "nodes", "segments", "arcs", "inventory", "manifest", "result"}


def test_example_semantic_identity_is_independent_of_record_order():
    fixture = ROOT / "pipeline/fixtures/network-package-v1"
    manifest = package.read_json(fixture / "manifest.example.json")
    rows = {name: package.read_json(fixture / f"{name}.json")[name] for name in ("nodes", "segments", "arcs")}
    assert graph_digest(manifest["identity"], manifest["coverage"], manifest["diagnostics"], **rows) == manifest["graph_id"]
    reverse = {key: list(reversed(value)) for key, value in rows.items()}
    assert graph_digest(manifest["identity"], manifest["coverage"], manifest["diagnostics"], **reverse) == manifest["graph_id"]


@pytest.mark.parametrize("payload", ['{"a":1,"a":2}', '{"a":NaN}'])
def test_untrusted_json_rejects_duplicate_keys_and_nonfinite_values(payload):
    path = ROOT / "pipeline/tools/tests" / f".invalid-{uuid.uuid4().hex}.json"
    try:
        path.write_text(payload, encoding="utf-8")
        with pytest.raises(package.PackageError):
            package.read_json(path)
    finally:
        path.unlink(missing_ok=True)


def test_unknown_data_fields_are_rejected_by_closed_manifest_schema():
    with pytest.raises(package.PackageError, match="manifest schema invalid"):
        package.schema_check({"unexpected": True}, "manifest")


def test_rebuilt_synthetic_release_keeps_semantics_and_rejects_corruption():
    staging_root = ROOT / "data/staging/prototype/package-test-runs"
    staging_root.mkdir(parents=True, exist_ok=True)
    output_root = staging_root / uuid.uuid4().hex
    output_root.mkdir()
    try:
        first, m1 = package.build_synthetic("fixture-rebuild-1", output_root)
        second, m2 = package.build_synthetic("fixture-rebuild-2", output_root)
        assert m1["graph_id"] == m2["graph_id"]
        assert m1["release_id"] != m2["release_id"]
        assert m1["files"]["nodes"]["sha256"] != m2["files"]["nodes"]["sha256"]
        qa = package.read_json(first / "qa.json")
        assert qa["packager_code_sha256"] == package.sha(Path(package.__file__))
        expected = package.read_json(output_root / "_expected-results" / "fixture-rebuild-1.json")
        package.schema_check(expected, "result")
        assert expected["manifest_sha256"] == package.sha(first / "manifest.json")
        assert expected["graph_id"] == m1["graph_id"]
        assert package.validate_release(first / "manifest.json")["counts"] == {"nodes": 3, "segments": 2, "arcs": 3}

        def refresh_descriptor(key):
            manifest = package.read_json(first / "manifest.json")
            payload = first / manifest["files"][key]["path"]
            manifest["files"][key]["bytes"] = payload.stat().st_size
            manifest["files"][key]["sha256"] = package.sha(payload)
            package.write_json(first / "manifest.json", manifest)

        manifest = package.read_json(first / "manifest.json")
        arcs = package.read_json(first / "arcs.json")
        arcs["arcs"][0]["direction"] = "reverse" if arcs["arcs"][0]["direction"] == "forward" else "forward"
        package.write_json(first / "arcs.json", arcs)
        refresh_descriptor("arcs")
        with pytest.raises(package.PackageError, match="arc endpoint mismatch"):
            package.validate_release(first / "manifest.json")

        nodes = {row["node_id"]: row["coordinate"] for row in package.read_json(first / "nodes.json")["nodes"]}
        segments = package.read_json(second / "segments.json")
        segments["release_id"] = m1["release_id"]
        segments["segments"][0]["to_node_id"] = "3"
        segments["segments"][0]["coordinates"][1] = nodes["3"]
        package.write_json(first / "segments.json", segments)
        arcs = package.read_json(second / "arcs.json")
        arcs["release_id"] = m1["release_id"]
        package.write_json(first / "arcs.json", arcs)
        refresh_descriptor("segments"); refresh_descriptor("arcs")
        with pytest.raises(package.PackageError, match="arc endpoint mismatch"):
            package.validate_release(first / "manifest.json")

        segments = package.read_json(second / "segments.json")
        segments["release_id"] = m1["release_id"]
        segments["segments"][0]["base_seconds"] += 1
        package.write_json(first / "segments.json", segments)
        refresh_descriptor("segments")
        with pytest.raises(package.PackageError, match="base cost mismatch"):
            package.validate_release(first / "manifest.json")

        corrupt = second / "arcs.json"
        corrupt.write_bytes(corrupt.read_bytes() + b" ")
        with pytest.raises(package.PackageError, match="file size/hash mismatch"):
            package.validate_release(second / "manifest.json")
    finally:
        resolved = output_root.resolve()
        assert resolved.is_relative_to(staging_root.resolve()) and not output_root.is_symlink()
        shutil.rmtree(resolved)

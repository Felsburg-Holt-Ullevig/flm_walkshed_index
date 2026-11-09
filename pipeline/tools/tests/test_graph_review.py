from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "pipeline/tools/review_graph.py"
spec = importlib.util.spec_from_file_location("graph_review", TOOL)
reviewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reviewer)


@pytest.fixture
def tmp_path():
    parent = ROOT / "data/staging/prototype/graph-review-tests"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as directory:
        yield Path(directory)


@pytest.mark.parametrize("tags,status", [
    ({}, "include"), ({"highway": "cycleway"}, "include"),
    ({"highway": "construction", "foot": "yes"}, "include"),
    ({"highway": "residential", "access": "no"}, "include"),
    ({"highway": "residential", "foot": "private"}, "include"),
    ({"highway": "path", "foot": "no"}, "exclude"),
    ({"highway": "motorway", "foot": "yes"}, "include"),
    ({"highway": "trunk", "foot": "designated"}, "include"),
    ({"highway": "motorway_link", "foot": "permissive"}, "include"),
    ({"highway": "trunk_link", "foot": "YES"}, "exclude"),
    ({"highway": "trunk", "access": "yes"}, "exclude"),
    ({"highway": "footway", "access:conditional": "no @ (Mo-Fr)"}, "include"),
])
def test_pinned_reference_policy_examples(tags, status):
    assert reviewer.reference_eligibility(tags) == status


@pytest.mark.parametrize("tags,expected", [
    ({"highway": "path"}, "footway"), ({"highway": "cycleway"}, "footway"),
    ({"highway": "residential", "footway": "sidewalk"}, "footway"),
    ({"sidewalk": "YES"}, "both"), ({"sidewalk": "left"}, "one-side"),
    ({"sidewalk": "separate"}, "none"), ({}, "unknown"),
])
def test_reference_sidewalk_examples(tags, expected):
    assert reviewer.reference_sidewalk(tags) == expected


def test_components_separate_weak_strong_parallel_and_coincident_identity():
    graph = reviewer.Components()
    graph.add("1", "2", [[0, 0], [.001, 0]], 100, "forward", "10")
    graph.add("1", "2", [[0, 0], [.001, 0]], 100, "forward", "11")
    graph.add("3", "9007199254740993", [[.001, 0], [.001, .001]], 200, "both", "12")
    result = graph.finish([-.1, -.1, .1, .1])
    assert result == {"nodes": 4, "source_segments": 3, "directed_arcs": 4, "weak_components": 2, "strong_components": 3, "largest_weak_nodes": 2, "largest_strong_nodes": 2, "components_with_two_nodes": 2, "length_ft": 400}
    assert graph.weak["2"] != graph.weak["3"]
    assert graph.strong["1"] != graph.strong["2"]
    assert graph.strong["3"] == graph.strong["9007199254740993"]


def test_components_are_order_independent():
    pairs = [("2", "3", [[.001, 0], [.002, 0]], 100, "both", "10"), ("1", "2", [[0, 0], [.001, 0]], 100, "both", "11")]
    a, b = reviewer.Components(), reviewer.Components()
    for pair in pairs:
        a.add(*pair)
    for pair in reversed(pairs):
        b.add(*pair)
    assert a.finish([-.1, -.1, .1, .1]) == b.finish([-.1, -.1, .1, .1])
    assert a.weak == b.weak and a.strong == b.strong


def test_empty_components():
    graph = reviewer.Components()
    assert graph.finish([0, 0, 1, 1])["weak_components"] == 0
    assert reviewer._gaps(graph)["candidate_pairs"] == 0


def test_inconsistent_source_coordinates_fail():
    graph = reviewer.Components()
    graph.add("1", "2", [[0, 0], [1, 0]], 100, "both", "10")
    with pytest.raises(ValueError, match="coordinates disagree"):
        graph.add("2", "3", [[0, 0], [1, 0]], 100, "both", "11")


def test_endpoint_gap_screen_is_diagnostic_and_does_not_join():
    graph = reviewer.Components()
    graph.add("1", "2", [[-105, 39.75], [-105, 39.751]], 300, "both", "10")
    graph.add("3", "4", [[-105, 39.75101], [-105, 39.752]], 300, "both", "11")
    graph.finish([-106, 39, -104, 40])
    gaps = reviewer._gaps(graph)
    assert gaps["candidate_pairs"] == 1
    assert 3 < gaps["nearest_pairs"][0]["distance_ft"] < 4
    assert graph.weak["2"] != graph.weak["3"]


def test_review_rejects_corrupt_graph_manifest_before_analysis(tmp_path):
    from flm_pipeline.classification import _write_json
    from flm_pipeline.code_identity import code_identity
    tmp_path.mkdir(exist_ok=True)
    graph = tmp_path / "graph"; graph.mkdir()
    (graph / "arcs.jsonl").write_text("changed")
    _write_json(graph / "run-report.json", {"report_version": "experimental-routing-graph-1", "checks": {"passed": True}, "implementation_identity": code_identity(), "output_files": {"arcs.jsonl": {"bytes": 7, "sha256": "0" * 64}}})
    with pytest.raises(ValueError, match="hash/size mismatch"):
        reviewer.review(graph, tmp_path, tmp_path / "output")


def test_reference_functions_match_pinned_javascript_if_local_evidence_available():
    # The mechanical comparison is also checked against the actual pinned functions;
    # absence of local evidence is explicit in a fresh synthetic-only environment.
    reference = ROOT / "data/staging/prototype/reference-6068f1b"
    if not reference.exists():
        pytest.skip("Pinned external reference cache is local prototype evidence")
    cases = [{"highway": highway, "foot": foot, "sidewalk": sidewalk} for highway in ["", "residential", "motorway", "cycleway", "construction"] for foot in ["", "yes", "no", "private", "permissive"] for sidewalk in ["", "YES", "separate", "left"]]
    harness = r'''
const fs = require('node:fs'), vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const road = fs.readFileSync(input.road, 'utf8'), audit = fs.readFileSync(input.audit, 'utf8');
const fn = name => road.match(new RegExp('function '+name+'\\([^]*?\\n  }'))[0];
const forbidden = road.match(/var PED_FORBIDDEN_HWY = \{[^]*?\};/)[0];
const context = { window: {App: {}} }; vm.createContext(context);
vm.runInContext(forbidden + '\n' + fn('isPedForbidden'), context);
vm.runInContext(audit, context);
console.log(JSON.stringify(input.cases.map(tags => [context.isPedForbidden(tags.highway, tags.foot) ? 'exclude' : 'include', context.window.WalkAudit.classifySidewalk({hwy:tags.highway,footway:tags.footway,sidewalk:tags.sidewalk})])));
'''
    result = subprocess.run(["node", "-e", harness], input=json.dumps({"road": str(reference / "road-network.js"), "audit": str(reference / "walk-audit.js"), "cases": cases}), text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == [[reviewer.reference_eligibility(tags), reviewer.reference_sidewalk(tags)] for tags in cases]


def test_raw_output_rejected(tmp_path):
    with pytest.raises(ValueError, match="outside raw inputs"):
        reviewer.review(tmp_path, tmp_path, ROOT / "data/raw/forbidden-review")


def test_real_fixture_classification_graph_review_roundtrip(tmp_path, monkeypatch):
    import hashlib
    sys.path.insert(0, str(ROOT / "pipeline/tests"))
    from test_classification import _fixture_extraction
    from flm_pipeline.classification import run_classification, _write_json
    from flm_pipeline.graph import build_graph
    extraction = _fixture_extraction(tmp_path)
    policy = ROOT / "pipeline/config/pedestrian-policy.example.toml"
    code, result = run_classification(extraction, policy, tmp_path / "classified", staging_root=tmp_path / "class-stage")
    assert code == 0
    classification = (ROOT / result["run_report"]).parent
    graph = tmp_path / "graph"
    report = build_graph(extraction, classification, policy, graph)
    _write_json(graph / "run-report.json", report)
    cache = tmp_path / "reference"; cache.mkdir()
    expected = {}
    for name in reviewer.REFERENCE_BLOBS:
        payload = b"synthetic reference fixture\n"
        (cache / name).write_bytes(payload)
        expected[name] = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
    monkeypatch.setattr(reviewer, "REFERENCE_BLOBS", expected)
    output = tmp_path / "review"
    reviewed = reviewer.review(graph, cache, output, progress=lambda *args, **kwargs: None)
    assert reviewed["scenarios"]["accepted"]["source_segments"] == 0
    assert reviewed["scenarios"]["reference"]["source_segments"] == 4
    assert sum(row["source_segments"] for row in reviewed["transitions"]) == 5
    assert all(reviewed["checks"].values())
    assert (output / "comparison.jsonl").exists()

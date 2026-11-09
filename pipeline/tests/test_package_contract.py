"""Task 5.1 fixture checks, separate from the production package validator.

The small evaluator covers only authored fixture keywords and fails closed on
others. Production validation uses jsonschema in package_network.py.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline/tools"))
from package_contract_semantics import graph_digest

SCHEMAS = ROOT / "contracts/network-package/v1"
FIXTURE = ROOT / "pipeline/fixtures/network-package-v1"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def check(value, schema):
    if schema is False:
        raise ValueError("Forbidden item")
    allowed = {"$schema", "$id", "$defs", "$ref", "type", "properties", "required", "additionalProperties", "items", "prefixItems", "minItems", "maxItems", "uniqueItems", "minimum", "maximum", "exclusiveMinimum", "minLength", "maxLength", "pattern", "const", "enum", "anyOf"}
    if schema.keys() - allowed:
        raise ValueError("Unsupported design-check keyword")
    if "$ref" in schema:
        file, pointer = schema["$ref"].split("#")
        target = load(SCHEMAS / file)
        for key in pointer.strip("/").split("/"):
            target = target[key]
        return check(value, target)
    if "anyOf" in schema:
        for alternative in schema["anyOf"]:
            try:
                check(value, alternative)
                return
            except ValueError:
                pass
        raise ValueError("No allowed alternative")
    if "const" in schema and (value != schema["const"] or type(value) is bool and type(schema["const"]) is not bool):
        raise ValueError("Wrong constant")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Wrong enum")
    types = {"object": lambda x: type(x) is dict, "array": lambda x: type(x) is list, "string": lambda x: type(x) is str, "integer": lambda x: type(x) in (int, float) and x % 1 == 0, "number": lambda x: type(x) in (int, float), "null": lambda x: x is None}
    if "type" in schema and not types[schema["type"]](value):
        raise ValueError("Wrong type")
    if type(value) is dict:
        if set(schema.get("required", [])) - value.keys():
            raise ValueError("Missing field")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and value.keys() - properties.keys():
            raise ValueError("Unknown field")
        for key in value.keys() & properties.keys():
            check(value[key], properties[key])
    if type(value) is list:
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            raise ValueError("Array length")
        if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in value}) != len(value):
            raise ValueError("Duplicate item")
        prefix = schema.get("prefixItems", [])
        for index, item in enumerate(value):
            check(item, prefix[index] if index < len(prefix) else schema.get("items", {}))
    if type(value) is str:
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            raise ValueError("String length")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ValueError("Pattern")
    if type(value) in (int, float):
        if value < schema.get("minimum", -float("inf")) or value > schema.get("maximum", float("inf")) or value <= schema.get("exclusiveMinimum", -float("inf")):
            raise ValueError("Number bounds")


@pytest.mark.parametrize("kind,file", [("manifest", "manifest.example.json"), ("nodes", "nodes.json"), ("segments", "segments.json"), ("arcs", "arcs.json"), ("inventory", "inventory.json"), ("result", "expected-result.json")])
def test_examples_match_authored_schema_keywords(kind, file):
    check(load(FIXTURE / file), load(SCHEMAS / f"{kind}.schema.json"))


@pytest.mark.parametrize("mutation", ["version", "numeric_id", "coordinate", "unknown_field", "direction"])
def test_schema_negative_examples(mutation):
    kind = "arcs" if mutation == "direction" else "nodes"
    data = load(FIXTURE / f"{kind}.json")
    if mutation == "version":
        data["schema_version"] = "flm-nodes-999"
    elif mutation == "numeric_id":
        data["nodes"][0]["node_id"] = 1
    elif mutation == "coordinate":
        data["nodes"][0]["coordinate"] = [200, 0]
    elif mutation == "unknown_field":
        data["unexpected"] = True
    else:
        data["arcs"][0]["direction"] = "both"
    with pytest.raises(ValueError):
        check(data, load(SCHEMAS / f"{kind}.schema.json"))


def test_fixture_membership_geometry_hashes_and_literal_arithmetic():
    manifest = load(FIXTURE / "manifest.example.json")
    rows = {}
    for kind in ("nodes", "segments", "arcs"):
        file = FIXTURE / f"{kind}.json"
        envelope = load(file)
        assert envelope["release_id"] == manifest["release_id"]
        assert envelope["graph_id"] == manifest["graph_id"]
        assert hashlib.sha256(file.read_bytes()).hexdigest() == manifest["files"][kind]["sha256"]
        assert len(file.read_bytes()) == manifest["files"][kind]["bytes"]
        rows[kind] = envelope[kind]
        assert len(rows[kind]) == manifest["counts"][kind]
    nodes = {r["node_id"]: r["coordinate"] for r in rows["nodes"]}
    segments = {r["candidate_id"]: r for r in rows["segments"]}
    expected_arcs = set()
    for cid, segment in segments.items():
        assert cid == f'way/{segment["way_id"]}/segment/{segment["sequence"]}'
        assert segment["coordinates"] == [nodes[segment["from_node_id"]], nodes[segment["to_node_id"]]]
        assert segment["base_seconds"] == pytest.approx(segment["length_ft"] * .24384, abs=1e-9)
        for direction in (["forward", "reverse"] if segment["direction"] == "both" else [segment["direction"]]):
            expected_arcs.add(f"{cid}/{direction}")
    assert {a["edge_id"] for a in rows["arcs"]} == expected_arcs
    for arc in rows["arcs"]:
        segment = segments[arc["candidate_id"]]
        a, b = segment["from_node_id"], segment["to_node_id"]
        assert (arc["from_node_id"], arc["to_node_id"]) == ((a,b) if arc["direction"] == "forward" else (b,a))
    result = load(FIXTURE / "expected-result.json")
    assert result["request"]["time_budget_seconds"] == pytest.approx(150 * .24384)
    assert result["outputs"]["reached_nodes"] == [{"node_id": "1", "seconds": 0}, {"node_id": "2", "seconds": 24.384}]
    assert result["outputs"]["intervals"] == [{"candidate_id": "way/10/segment/0", "start_ft": 0, "end_ft": 100}, {"candidate_id": "way/10/segment/1", "start_ft": 0, "end_ft": 50}]
    assert result["outputs"]["unique_source_length_ft"] == 150
    assert result["manifest_sha256"] == hashlib.sha256((FIXTURE / "manifest.example.json").read_bytes()).hexdigest()
    assert manifest["identity"]["source_inventory_sha256"] == hashlib.sha256((FIXTURE / "inventory.json").read_bytes()).hexdigest()
    digest = graph_digest(manifest["identity"], manifest["coverage"], manifest["diagnostics"], **rows)
    assert digest == manifest["graph_id"]
    assert digest == graph_digest(manifest["identity"], manifest["coverage"], manifest["diagnostics"], **{k: list(reversed(v)) for k,v in rows.items()})
    changed = copy.deepcopy(rows)
    changed["segments"][0]["length_ft"] += 1
    assert digest != graph_digest(manifest["identity"], manifest["coverage"], manifest["diagnostics"], **changed)


@pytest.mark.parametrize("field", ["connectivity", "direction", "cost"])
def test_semantic_identity_changes_for_connectivity_direction_and_cost(field):
    manifest = load(FIXTURE / "manifest.example.json")
    rows = {name: load(FIXTURE / f"{name}.json")[name] for name in ("nodes", "segments", "arcs")}
    original = graph_digest(manifest["identity"], manifest["coverage"], manifest["diagnostics"], **rows)
    changed = copy.deepcopy(rows)
    if field == "connectivity":
        changed["segments"][0]["to_node_id"] = "3"
    elif field == "direction":
        changed["segments"][0]["direction"] = "forward"
    else:
        changed["segments"][0]["base_seconds"] += 1
    assert original != graph_digest(manifest["identity"], manifest["coverage"], manifest["diagnostics"], **changed)


def test_design_checker_rejects_unhandled_schema_keywords():
    with pytest.raises(ValueError, match="Unsupported"):
        check({}, {"unevaluatedProperties": False})

"""Validate, package, and locally promote experimental routing releases.

This adapter consumes frozen graph artifacts. It never reads or modifies raw OSM,
rebuilds upstream policy outputs, publishes a release, or changes accepted hashes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from pyproj import Geod

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "contracts/network-package/v1"
SCHEMAS = {p.stem.removesuffix(".schema"): json.loads(p.read_text(encoding="utf-8")) for p in SCHEMA_DIR.glob("*.schema.json")}
REGISTRY = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in SCHEMAS.values())
APPROVED = ROOT / "docs/planning/2026-11-02/active-regional-run.json"
SOURCE_URL = "https://download.geofabrik.de/north-america/us/colorado.html"
COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
GEOD = Geod(ellps="WGS84")
MAX = {"manifest": 1 * 1024**2, "json": 256 * 1024**2, "browser_json": 512 * 1024**2, "package": 4 * 1024**3, "nodes": 600000, "segments": 700000, "arcs": 1400000}


class PackageError(RuntimeError):
    pass


def need(ok, message):
    if not ok:
        raise PackageError(message)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


PACKAGER_CODE_SHA256 = sha(Path(__file__).resolve())


def pairs(pairs_):
    out = {}
    for key, value in pairs_:
        if key in out:
            raise PackageError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def constant(value):
    raise PackageError(f"invalid JSON number: {value}")


def depth(value, level=0):
    need(level <= 32, "JSON nesting exceeds 32 levels")
    if isinstance(value, (dict, list)):
        for item in value.values() if isinstance(value, dict) else value:
            depth(item, level + 1)
    elif isinstance(value, int) and not isinstance(value, bool):
        need(abs(value) <= 9007199254740991, "unsafe JSON integer; source identifiers must be strings")
    elif isinstance(value, float):
        need(math.isfinite(value), "nonfinite JSON number")


def read_json(path: Path, limit=MAX["json"]):
    need(path.is_file() and not path.is_symlink(), f"missing or symlinked file: {path.name}")
    need(path.stat().st_size <= limit, f"file exceeds byte limit: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"invalid UTF-8 JSON in {path.name}: {exc}") from exc
    depth(value)
    return value


def validate_schema_files():
    for name, schema in SCHEMAS.items():
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, registry=REGISTRY)
    return {name: Draft202012Validator(schema, registry=REGISTRY) for name, schema in SCHEMAS.items()}


VALIDATORS = validate_schema_files()


def schema_check(value, name):
    errors = sorted(VALIDATORS[name].iter_errors(value), key=lambda e: (list(map(str, e.absolute_path)), e.message))
    need(not errors, f"{name} schema invalid at {list(errors[0].absolute_path)}: {errors[0].message}" if errors else "")


def tagged(value):
    if value is None: return ["null"]
    if isinstance(value, bool): return ["bool", value]
    if isinstance(value, (int, float)):
        need(math.isfinite(value), "nonfinite semantic number")
        return ["number", struct.pack(">d", 0.0 if value == 0 else value).hex()]
    if isinstance(value, str):
        need(value.isascii(), "semantic identity v1 requires ASCII strings")
        return ["string", value]
    if isinstance(value, list): return ["array", [tagged(item) for item in value]]
    if isinstance(value, dict): return ["object", [[key, tagged(value[key])] for key in sorted(value)]]
    raise PackageError("unsupported semantic value")


def canonical_value(value):
    return json.dumps(tagged(value), separators=(",", ":"), ensure_ascii=True).encode("ascii")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def bbox_ok(bbox):
    return isinstance(bbox, list) and len(bbox) == 4 and all(type(x) in (int, float) and math.isfinite(x) for x in bbox) and -180 <= bbox[0] < bbox[2] <= 180 and -90 <= bbox[1] < bbox[3] <= 90


def close(a, b):
    return isinstance(a, (int, float)) and not isinstance(a, bool) and math.isfinite(a) and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9)


def file_descriptor(path, records):
    size = path.stat().st_size
    return {"path": path.name, "bytes": size, "sha256": sha(path), "records": records}


def inventory_for(source_inventory, release_id, *, synthetic=False):
    if synthetic:
        return {"schema_version": source_inventory["schema_version"], "inventory_id": source_inventory.get("inventory_id", "synthetic-f01-inventory-1"), "sources": source_inventory["sources"]}
    osm = source_inventory["sources"]["osm"]
    return {
        "schema_version": "flm-inventory-1", "inventory_id": "osm-colorado-2026-11-02-v1",
        "sources": [{
            "source_id": "osm-colorado-20261102", "kind": "osm", "sha256": osm["sha256"], "bytes": osm["bytes"],
            "url": SOURCE_URL, "downloaded_at": "2026-11-02 (date supplied by developer; time not supplied)",
            "claimed_vintage": None, "observed_vintage": osm["observed_header_vintage"],
            "provenance_status": "retrieval page and calendar date supplied by developer; exact download time absent; header timestamp is data vintage, not download time",
            "license": "Open Database License 1.0 (ODbL-1.0), as stated for OpenStreetMap/Geofabrik downloads",
            "attribution": "© OpenStreetMap contributors",
            "redistribution": "not_cleared", "excluded_records": 0, "unknown_records": 0, "reason_counts": [],
        }],
    }


def source_license_text(*, synthetic=False):
    if synthetic:
        return "Synthetic fixture data only. No external map source or attribution applies.\n"
    return ("OpenStreetMap data attribution\n\n© OpenStreetMap contributors\n"
            "OpenStreetMap data is available under the Open Database License 1.0 (ODbL-1.0).\n"
            f"License and attribution information: {COPYRIGHT_URL}\n"
            f"ODbL 1.0 legal text: {LICENSE_URL}\n"
            f"Source region page: {SOURCE_URL}\n\n"
            "The source file retrieval page and download date (2026-11-02) were supplied by the developer. "
            "The precise download time is unknown. The PBF header records 2026-11-01T21:21:36Z as the source data replication vintage; it is not a download time. "
            "This local prototype package is not cleared for public redistribution or client delivery.\n")


def seed_db(db, graph_dir, expected_counts, *, synthetic=False):
    db.executescript("""
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE;
        CREATE TABLE nodes(id TEXT PRIMARY KEY, row TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE segments(id TEXT PRIMARY KEY, row TEXT NOT NULL, dirs TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE arcs(id TEXT PRIMARY KEY, candidate TEXT NOT NULL, direction TEXT NOT NULL, row TEXT NOT NULL) WITHOUT ROWID;
        CREATE INDEX arcs_candidate_idx ON arcs(candidate);
    """)
    counts = Counter(); reasons = Counter(); relation_unsupported = 0; unresolved = 0
    with (graph_dir / "nodes.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line); node_id = row["node_id"]
            need(re.fullmatch(r"[1-9][0-9]{0,19}", node_id) and -180 <= row["lon"] <= 180 and -90 <= row["lat"] <= 90, "invalid source node")
            compact = {"node_id": node_id, "coordinate": [row["lon"], row["lat"]]}
            db.execute("INSERT INTO nodes VALUES (?,?)", (node_id, json.dumps(compact, separators=(",", ":"))))
            counts["nodes"] += 1
    with (graph_dir / "segments.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line); counts["candidates"] += 1
            need(row.get("eligibility") in {"include", "exclude", "unknown"}, "invalid candidate disposition")
            if row["eligibility"] != "include":
                counts[row["eligibility"]] += 1
                for reason in set(row.get("reason_codes", [])):
                    reasons[(row["eligibility"], reason)] += 1
                continue
            cid = row["candidate_id"]
            need(cid == f"way/{row['way_id']}/segment/{row['sequence']}", f"candidate identity mismatch: {cid}")
            need(row["direction"] in {"both", "forward", "reverse"}, f"included candidate has invalid direction: {cid}")
            need(len(row["coordinates"]) == 2 and row["from_node_id"] != row["to_node_id"], f"invalid included geometry: {cid}")
            for node_id, coord in ((row["from_node_id"], row["coordinates"][0]), (row["to_node_id"], row["coordinates"][1])):
                record = db.execute("SELECT row FROM nodes WHERE id=?", (node_id,)).fetchone()
                need(record is not None, f"unresolved included endpoint {node_id}")
                node = json.loads(record[0])
                need(coord == node["coordinate"], f"segment coordinates do not match nodes: {cid}")
            if not synthetic:
                _, _, meters = GEOD.inv(*row["coordinates"][0], *row["coordinates"][1])
                feet = meters / 0.3048
                need(close(row["length_ft"], feet) and close(row["base_seconds"], feet * 0.24384), f"length/cost mismatch: {cid}")
            else:
                need(close(row["base_seconds"], row["length_ft"] * .24384), f"synthetic cost mismatch: {cid}")
            compact = {"candidate_id": cid, "way_id": row["way_id"], "sequence": row["sequence"], "from_node_id": row["from_node_id"], "to_node_id": row["to_node_id"], "coordinates": row["coordinates"], "length_ft": row["length_ft"], "base_seconds": row["base_seconds"], "direction": row["direction"]}
            dirs = "forward,reverse" if row["direction"] == "both" else row["direction"]
            db.execute("INSERT INTO segments VALUES (?,?,?,?,?)", (cid, json.dumps(compact, separators=(",", ":")), dirs, row["from_node_id"], row["to_node_id"]))
            counts["segments"] += 1
    with (graph_dir / "arcs.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line); cid = row["candidate_id"]
            item = db.execute("SELECT row,dirs FROM segments WHERE id=?", (cid,)).fetchone()
            need(item is not None, f"arc refers to missing included segment: {cid}")
            segment = json.loads(item[0]); direction = row["direction"]
            need(direction in item[1].split(","), f"unexpected direction: {row['edge_id']}")
            reverse = direction == "reverse"
            expected = (segment["to_node_id"], segment["from_node_id"]) if reverse else (segment["from_node_id"], segment["to_node_id"])
            geometry = list(reversed(segment["coordinates"])) if reverse else segment["coordinates"]
            need(row["edge_id"] == f"{cid}/{direction}" and (row["from_node_id"], row["to_node_id"]) == expected and row["coordinates"] == geometry and close(row["length_ft"], segment["length_ft"]) and close(row["base_seconds"], segment["base_seconds"]), f"arc mismatch: {row.get('edge_id')}")
            arc = {"edge_id": row["edge_id"], "candidate_id": cid, "from_node_id": expected[0], "to_node_id": expected[1], "direction": direction}
            db.execute("INSERT INTO arcs VALUES (?,?,?,?)", (arc["edge_id"], cid, direction, json.dumps(arc, separators=(",", ":"))))
            counts["arcs"] += 1
    for cid, dirs, actual_rows in db.execute("SELECT s.id,s.dirs,group_concat(a.direction,',') FROM segments s LEFT JOIN arcs a ON a.candidate=s.id GROUP BY s.id"):
        expected = set(dirs.split(","))
        actual = set(actual_rows.split(",")) if actual_rows else set()
        need(actual == expected, f"arc membership mismatch: {cid}")
    for row, in db.execute("SELECT row FROM arcs"):
        arc = json.loads(row)
        need(db.execute("SELECT 1 FROM nodes WHERE id=?", (arc["from_node_id"],)).fetchone() and db.execute("SELECT 1 FROM nodes WHERE id=?", (arc["to_node_id"],)).fetchone(), "arc endpoint absent from nodes")
    with (graph_dir / "relations-audit.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line); relation_unsupported += bool(row["unsupported"]); unresolved += row["unresolved_members"]
    need(counts["nodes"] == expected_counts["nodes"] and counts["segments"] == expected_counts["candidates_by_eligibility"]["include"] and counts["arcs"] == expected_counts["directed_arcs"] and counts["candidates"] == expected_counts["candidates"], "graph record counts disagree with frozen report")
    return counts, reasons, relation_unsupported, unresolved


def semantic_hash(db, identity, coverage, diagnostics):
    fixed = {"coverage": coverage, "diagnostics": diagnostics, "identity": identity, "semantic_version": "flm-graph-semantic-1"}
    names = {"nodes": "SELECT row FROM nodes ORDER BY id COLLATE BINARY", "segments": "SELECT row FROM segments ORDER BY id COLLATE BINARY", "arcs": "SELECT row FROM arcs ORDER BY id COLLATE BINARY"}
    h = hashlib.sha256(); h.update(b'["object",[')
    keys = sorted([*fixed, "nodes", "segments", "arcs"])
    first = True
    for key in keys:
        if not first: h.update(b",")
        first = False; h.update(b"["); h.update(json.dumps(key, ensure_ascii=True).encode("ascii")); h.update(b",")
        if key in names:
            h.update(b'["array",['); arr_first = True
            for (text,) in db.execute(names[key]):
                if not arr_first: h.update(b",")
                arr_first = False; h.update(canonical_value(json.loads(text)))
            h.update(b"]]")
        else:
            value = fixed[key]
            h.update(canonical_value(value))
        h.update(b"]")
    h.update(b"]]")
    return h.hexdigest()


def iter_rows(db, table):
    for (text,) in db.execute(f"SELECT row FROM {table} ORDER BY id COLLATE BINARY"):
        yield json.loads(text)


def _ws(text, pos):
    while pos < len(text) and text[pos] in " \t\r\n": pos += 1
    return pos


@contextmanager
def array_envelope(path, array_key):
    """Read one array member at a time, retaining only the bounded file text and row."""
    need(path.stat().st_size <= MAX["json"], f"file exceeds JSON byte cap: {path.name}")
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder(object_pairs_hook=pairs, parse_constant=constant)
    pos = _ws(text, 0); need(pos < len(text) and text[pos] == "{", f"expected object envelope in {path.name}"); pos += 1
    header = {}; keys = set(); rows = None
    while True:
        pos = _ws(text, pos)
        if pos < len(text) and text[pos] == "}": pos += 1; break
        key, pos = decoder.raw_decode(text, pos); need(isinstance(key, str) and key not in keys, f"duplicate/invalid envelope key in {path.name}"); keys.add(key)
        pos = _ws(text, pos); need(text[pos] == ":", f"invalid JSON envelope in {path.name}"); pos = _ws(text, pos + 1)
        if key == array_key:
            need(text[pos] == "[", f"expected {array_key} array"); pos += 1
            def generate():
                nonlocal pos
                first = True
                while True:
                    pos = _ws(text, pos)
                    if pos < len(text) and text[pos] == "]": pos += 1; break
                    if not first:
                        need(text[pos] == ",", f"invalid {array_key} separator"); pos = _ws(text, pos + 1)
                    row, pos = decoder.raw_decode(text, pos); depth(row); yield row; first = False
                nonlocal_header_check = True
            rows = generate()
            # Consume generator fully before returning; subsequent envelope properties follow its array.
            yield header, rows
            pos = _ws(text, pos)
            if pos < len(text) and text[pos] == ",":
                pos = _ws(text, pos + 1); continue
            need(pos < len(text) and text[pos] == "}", f"invalid envelope terminator in {path.name}"); pos += 1; break
        else:
            value, pos = decoder.raw_decode(text, pos); depth(value); header[key] = value
            pos = _ws(text, pos)
            if pos < len(text) and text[pos] == ",": pos = _ws(text, pos + 1); continue
            need(pos < len(text) and text[pos] == "}", f"invalid envelope terminator in {path.name}"); pos += 1; break
    pos = _ws(text, pos); need(pos == len(text), f"trailing JSON data in {path.name}")
    need(rows is not None and keys == {"schema_version", "release_id", "graph_id", array_key}, f"invalid envelope fields in {path.name}")
    need(header == {"schema_version": f"flm-{array_key}-1", "release_id": header.get("release_id"), "graph_id": header.get("graph_id")}, f"invalid envelope schema version in {path.name}")
    schema_check({**header, array_key: []}, array_key)


def validate_graph_payloads(root, manifest):
    dbfile = Path(tempfile.gettempdir()) / f"flm-package-validate-{uuid.uuid4().hex}.sqlite"
    db = sqlite3.connect(dbfile)
    try:
        db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; CREATE TABLE nodes(id TEXT PRIMARY KEY,row TEXT) WITHOUT ROWID; CREATE TABLE segments(id TEXT PRIMARY KEY,row TEXT,dirs TEXT,from_id TEXT,to_id TEXT) WITHOUT ROWID; CREATE TABLE arcs(id TEXT PRIMARY KEY,candidate TEXT,direction TEXT,row TEXT) WITHOUT ROWID; CREATE INDEX arc_candidate ON arcs(candidate);")
        actual_counts = Counter(); headers = []
        for key in ("nodes", "segments", "arcs"):
            path = root / manifest["files"][key]["path"]
            headers.append((key, path))
            with array_envelope(path, key) as (header, rows):
                for row in rows:
                    schema = SCHEMAS[key]["properties"][key]["items"]
                    VALIDATORS[key].evolve(schema=schema).validate(row)
                    if key == "nodes":
                        need(re.fullmatch(r"[1-9][0-9]{0,19}", row["node_id"]) is not None, "node ID must be a decimal string")
                        db.execute("INSERT INTO nodes VALUES (?,?)", (row["node_id"], json.dumps(row, separators=(",", ":"))))
                    elif key == "segments":
                        cid = row["candidate_id"]
                        need(cid == f"way/{row['way_id']}/segment/{row['sequence']}", f"candidate identity mismatch: {cid}")
                        a = db.execute("SELECT row FROM nodes WHERE id=?", (row["from_node_id"],)).fetchone(); b = db.execute("SELECT row FROM nodes WHERE id=?", (row["to_node_id"],)).fetchone()
                        need(a and b and row["coordinates"] == [json.loads(a[0])["coordinate"], json.loads(b[0])["coordinate"]], f"geometry/endpoints mismatch: {cid}")
                        if manifest["identity"]["length_model"] == "wgs84_geodesic_international_ft":
                            _, _, meters = GEOD.inv(*row["coordinates"][0], *row["coordinates"][1]); length = meters / .3048
                            need(close(row["length_ft"], length), f"geodesic length mismatch: {cid}")
                        else:
                            length = row["length_ft"]
                        need(close(row["base_seconds"], length * .24384), f"base cost mismatch: {cid}")
                        dirs = "forward,reverse" if row["direction"] == "both" else row["direction"]
                        db.execute("INSERT INTO segments VALUES (?,?,?,?,?)", (cid, json.dumps(row, separators=(",", ":")), dirs, row["from_node_id"], row["to_node_id"]))
                    else:
                        cid = row["candidate_id"]; seg = db.execute("SELECT row,dirs FROM segments WHERE id=?", (cid,)).fetchone()
                        need(seg is not None and row["direction"] in seg[1].split(","), f"arc candidate/direction missing: {row['edge_id']}")
                        s = json.loads(seg[0]); reverse = row["direction"] == "reverse"
                        endpoints = (s["to_node_id"], s["from_node_id"]) if reverse else (s["from_node_id"], s["to_node_id"])
                        need(row["edge_id"] == cid + "/" + row["direction"] and (row["from_node_id"], row["to_node_id"]) == endpoints, f"arc endpoint mismatch: {row['edge_id']}")
                        db.execute("INSERT INTO arcs VALUES (?,?,?,?)", (row["edge_id"], cid, row["direction"], json.dumps(row, separators=(",", ":"))))
                    actual_counts[key] += 1
                    need(actual_counts[key] <= MAX[key], f"{key} record limit exceeded")
                need(header["release_id"] == manifest["release_id"] and header["graph_id"] == manifest["graph_id"], f"{key} envelope binding mismatch")
            need(actual_counts[key] == manifest["files"][key]["records"], f"{key} record count mismatch")
        need(db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == manifest["counts"]["nodes"], "node count mismatch")
        need(db.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == manifest["counts"]["segments"], "segment count mismatch")
        need(db.execute("SELECT COUNT(*) FROM arcs").fetchone()[0] == manifest["counts"]["arcs"], "arc count mismatch")
        for cid, dirs, actual in db.execute("SELECT s.id,s.dirs,group_concat(a.direction,',') FROM segments s LEFT JOIN arcs a ON a.candidate=s.id GROUP BY s.id"):
            need(set(dirs.split(",")) == (set(actual.split(",")) if actual else set()), f"arc membership mismatch: {cid}")
        actual_id = semantic_hash(db, manifest["identity"], manifest["coverage"], manifest["diagnostics"])
        need(actual_id == manifest["graph_id"], "semantic graph identity mismatch")
        for key in ("nodes", "segments", "arcs"):
            need(manifest["counts"][key] <= MAX[key], f"{key} record cap exceeded")
        used_nodes = db.execute("SELECT COUNT(DISTINCT node_id) FROM (SELECT from_id AS node_id FROM segments UNION ALL SELECT to_id AS node_id FROM segments)").fetchone()[0]
        need(used_nodes == manifest["counts"]["nodes"], "unused or missing graph nodes")
    finally:
        db.close(); dbfile.unlink(missing_ok=True)


def write_payload(path, schema_version, release_id, graph_id, table, db):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write('{"schema_version":' + json.dumps(schema_version) + ',"release_id":' + json.dumps(release_id) + ',"graph_id":' + json.dumps(graph_id) + ',"' + table + '":[')
        first = True
        for row in iter_rows(db, table):
            if not first: stream.write(",")
            first = False
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        stream.write("]}\n")


def bounded_package(directory, descriptors):
    total = 0
    for name, desc in descriptors.items():
        path = directory / desc["path"]
        size = path.stat().st_size; total += size
        if name in {"nodes", "segments", "arcs", "inventory", "qa"}:
            need(size <= MAX["json"], f"{name} exceeds per-file JSON cap")
    need(sum(descriptors[key]["bytes"] for key in ("nodes", "segments", "arcs", "inventory")) <= MAX["browser_json"], "required browser JSON exceeds total cap")
    need(total <= MAX["package"], "release exceeds total package cap")


def package(graph_dir, source_inventory_path, handoff_path, release_id, output_root, *, synthetic=False):
    need(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,159}", release_id) is not None and "/" not in release_id and ".." not in release_id, "invalid release ID")
    graph_dir = graph_dir.resolve(strict=True); output_root = output_root.resolve()
    source_inventory_path = source_inventory_path.resolve(strict=True)
    report_path = graph_dir / "run-report.json"
    report = read_json(report_path, MAX["manifest"])
    source_inventory = read_json(source_inventory_path, 8 * 1024 * 1024)
    need(report.get("report_version") == "experimental-routing-graph-1" and report.get("checks", {}).get("worker_exit_zero") is True and report.get("checks", {}).get("structural_validation") is True and report.get("checks", {}).get("gpkg_all_records_reopened") is True, "graph report is not a completed validated graph")
    need(report.get("status") in {"experimental_graph_complete", "incomplete_unknown_policy"}, "unsupported graph status")
    if not synthetic:
        handoff = read_json(handoff_path, 4 * 1024 * 1024)
        need(handoff.get("gate_4_status", "").startswith("accepted_"), "Gate 4 is not accepted")
        need(handoff.get("gate_4_status") == "accepted_limited_source_node_diagnostic_and_experimental_contract", "unexpected Gate 4 scope")
        need(report_path.relative_to(ROOT).as_posix() == handoff["graph_report"], "graph report is not the accepted frozen graph")
        need(sha(report_path) == handoff["graph_report_sha256"], "frozen graph report hash mismatch")
        for stage in ("extraction", "classification"):
            stage_dir = Path(report["inputs"][f"{stage}_directory"]).resolve(strict=True)
            accepted_dir = (ROOT / handoff[f"{stage}_directory"]).resolve(strict=True)
            expected_root = (ROOT / "data/generated/prototype").resolve(strict=True)
            need(stage_dir == accepted_dir and stage_dir.is_relative_to(expected_root), f"{stage} directory is not the accepted frozen stage")
            stage_hashes = report["inputs"][f"{stage}_hashes"]
            need("run-report.json" in stage_hashes, f"{stage} run report hash is missing")
            for filename, expected_hash in stage_hashes.items():
                relative = Path(filename)
                need(not relative.is_absolute() and len(relative.parts) == 1 and relative.name == filename and relative.name not in {".", ".."}, f"unsafe frozen {stage} output path: {filename}")
                frozen_file = stage_dir / relative
                need(not frozen_file.is_symlink() and frozen_file.is_file() and sha(frozen_file) == expected_hash, f"frozen {stage} output hash mismatch: {filename}")
            accepted_report = (ROOT / handoff[f"{stage}_report"]).resolve(strict=True)
            need(accepted_report == stage_dir / "run-report.json" and sha(accepted_report) == stage_hashes["run-report.json"], f"accepted {stage} report identity mismatch")
            if handoff.get(f"{stage}_report_sha256"):
                need(sha(accepted_report) == handoff[f"{stage}_report_sha256"], f"accepted {stage} report hash mismatch")
        need(sha(source_inventory_path) == handoff["inventory_sha256"], "accepted source inventory hash mismatch")
        inventory_report_path = ROOT / handoff["inventory_report"]
        need(inventory_report_path.is_file(), "accepted inventory report is missing")
        inventory_report = read_json(inventory_report_path, MAX["manifest"])
        need(inventory_report.get("status") in {"pass", "pass_with_warnings"} and inventory_report.get("inventory_status") in {"pass", "pass_with_warnings"} and inventory_report.get("source_inventory_sha256") == handoff["inventory_sha256"], "accepted inventory report is incomplete or does not bind the source inventory")
        need(report.get("inputs", {}).get("source", {}).get("sha256") == handoff["source_sha256"], "graph and accepted OSM hashes differ")
        need(report.get("checks", {}).get("input_hashes_verified_before_after") is True and report.get("checks", {}).get("gpkg_all_records_reopened") is True, "frozen graph provenance/GIS validation failed")
        source = source_inventory["sources"]["osm"]
        inventory_osm = source
        need(inventory_osm.get("scan", {}).get("complete") is True and inventory_osm.get("expected_sha256_matches") is True, "accepted inventory does not record a complete, hash-matched OSM scan")
        source_rel = Path(report["inputs"]["source"]["path"])
        need(not source_rel.is_absolute() and not any(part in {".", ".."} for part in source_rel.parts), "raw source path is not a safe repository-relative path")
        source_path = (ROOT / source_rel).resolve(strict=True)
        need(source_path.is_relative_to((ROOT / "data/raw").resolve()) and not (ROOT / source_rel).is_symlink(), "raw source must remain a regular file under data/raw")
        need(source["sha256"] == handoff["source_sha256"] and report["inputs"]["source"]["sha256"] == source["sha256"], "accepted graph, inventory, and OSM source hashes differ")
        need(source["bytes"] == source_path.stat().st_size == report["inputs"]["source"]["bytes"] == inventory_osm.get("bytes"), "raw source, inventory, and graph byte counts differ")
        need(sha(source_path) == handoff["source_sha256"], "raw OSM source hash no longer matches the accepted pinned input")
        need(report.get("policy", {}).get("rule_version") == "pedestrian-policy-0.3" and report["policy"].get("travel_profile") == "general_pedestrian", "unexpected accepted policy")
        accepted = read_json(ROOT / "pipeline/fixtures/routing-reference-acceptance-v1.json", 1024 * 1024)
        need(sha(ROOT / "pipeline/fixtures/routing-reference-acceptance-v1.json") == handoff["routing_reference_acceptance_sha256"] and accepted["status"] == "accepted_experimental", "accepted routing reference changed")
        need(report["counts"]["candidates_by_eligibility"]["unknown"] > 0 or report["graph_status"] != "incomplete_unknown_policy", "incomplete status mismatch")
        need(report["inputs"]["source"]["sha256"] == handoff["source_sha256"], "source mismatch")
        need(report["output_files"].get("routing.gpkg") is not None and sha(graph_dir / "routing.gpkg") == report["output_files"]["routing.gpkg"]["sha256"], "source GIS checksum mismatch")
        for name, item in report["output_files"].items():
            source_file = graph_dir / name
            need(source_file.is_file() and source_file.stat().st_size == item["bytes"] and sha(source_file) == item["sha256"], f"frozen graph artifact mismatch: {name}")
        regional_path = ROOT / handoff["task_4_4_regional_report"]
        need(sha(regional_path) == handoff["task_4_4_regional_report_sha256"], "Task 4.4 report checksum mismatch")
        regional = read_json(regional_path, MAX["manifest"])
        need(regional.get("checks", {}).get("original_graph_payload_hashes_and_structure") is True and regional.get("checks", {}).get("original_graph_report_hash") is True and regional.get("settings", {}).get("coverage_readiness") == "not_established" and regional.get("inputs", {}).get("original_graph_report_sha256") == handoff["graph_report_sha256"], "Task 4.4 frozen diagnostic checks/status mismatch")
    need(output_root.is_relative_to(ROOT / "data/staging/prototype/network-package-candidates"), "worker output must remain under ignored package-candidate staging")
    stage_parent = ROOT / "data/staging/prototype/network-packages"
    final_parent = output_root
    stage_parent.mkdir(parents=True, exist_ok=True); final_parent.mkdir(parents=True, exist_ok=True)
    final = final_parent / release_id
    need(not final.exists(), f"release ID already exists: {release_id}")
    stage = stage_parent / f"{release_id}-{uuid.uuid4().hex[:8]}"
    stage.mkdir()
    db_path = stage / "build-index.sqlite"
    started = time.monotonic(); outcomes = []
    try:
        db = sqlite3.connect(db_path)
        try:
            counts, reasons, unsupported, unresolved = seed_db(db, graph_dir, report["counts"], synthetic=synthetic)
            outcomes.append("frozen graph identities/counts/costs/topology verified")
            need(unsupported == report["relations"]["unsupported"] and unresolved == report["relations"]["unresolved_members"], "relation audit counts mismatch")
            inventory = inventory_for(source_inventory, release_id, synthetic=synthetic)
            excluded = counts["exclude"]; unknown = counts["unknown"]
            if not synthetic:
                inventory["sources"][0]["excluded_records"] = excluded
                inventory["sources"][0]["unknown_records"] = unknown
                inventory["sources"][0]["reason_counts"] = [{"reason": f"candidate:{disp}:{code}", "count": value} for (disp, code), value in sorted(reasons.items())]
            # Rewrite provenance grain clearly: one inventory is OSM source evidence; candidate counts are reported in reason labels.
            write_json(stage / "inventory.json", inventory)
            input_inventory_sha = sha(stage / "inventory.json")
            if synthetic:
                example = read_json(ROOT / "pipeline/fixtures/network-package-v1/manifest.example.json", MAX["manifest"])
                coverage, diagnostics = example["coverage"], example["diagnostics"]
                identity = dict(example["identity"]); identity["source_inventory_sha256"] = input_inventory_sha
            else:
                inherited = [item for item in report["limitations"] if item != "Source extraction is historical hash-verified evidence; raw PBF not reprocessed or rehashed."]
                limitations = inherited + [
                    "The pinned raw OSM file was rehashed during packaging; extraction, classification and graph assembly were reused as accepted frozen stages.",
                    "Station entrance is unverified; origin tests use a source node.",
                    "Unknown candidates and unsupported restrictions prevent regional analytical promotion.",
                    "Source coverage remains not established; complete walksheds are not claimed.",
                    "Manual urban/rural GIS review remains incomplete.",
                ]
                coverage = {"core_bbox": report["coverage"]["core_bbox"], "extract_bbox": report["coverage"]["extract_bbox"], "selection": "node_inside_complete_way", "readiness": "not_established", "limitations": sorted(set(limitations))}
                diagnostics = {"unknown_candidates": unknown, "unsupported_restrictions": unsupported, "unresolved_relation_members": unresolved, "blockers": sorted([name for name, count in (("unknown_pedestrian_candidates", unknown), ("unsupported_walking_restrictions", unsupported), ("unresolved_relation_members", unresolved), ("source_coverage_not_established", 1)) if count]), "analytical_promotion": "blocked_experimental"}
                identity = {"graph_format": "flm-directed-graph-1", "rule_version": report["policy"]["rule_version"], "scenario_id": report["policy"]["scenario_id"], "rule_sha256": report["policy"]["authority_sha256"], "code_sha256": handoff["graph_implementation_sha256"], "config_sha256": report["policy"]["config_sha256"], "source_inventory_sha256": input_inventory_sha, "length_model": "wgs84_geodesic_international_ft", "seconds_per_foot": 0.24384}
            graph_id = semantic_hash(db, identity, coverage, diagnostics)
            for table, schema_name in (("nodes", "flm-nodes-1"), ("segments", "flm-segments-1"), ("arcs", "flm-arcs-1")):
                write_payload(stage / f"{table}.json", schema_name, release_id, graph_id, table, db)
            gpkg = stage / "routing.gpkg"; shutil.copyfile(graph_dir / "routing.gpkg", gpkg)
        finally:
            db.close()
        db_path.unlink(missing_ok=True)
        source_inventory_bytes = (stage / "inventory.json").stat().st_size
        report_payload = {"report_version": "flm-package-qa-1", "status": "complete_experimental", "release_id": release_id, "graph_id": graph_id, "packager_code_sha256": PACKAGER_CODE_SHA256, "producer_graph_report_sha256": sha(report_path), "producer_source_sha256": report.get("inputs", {}).get("source", {}).get("sha256") if not synthetic else None, "upstream_inventory_sha256": None if synthetic else sha(source_inventory_path), "source_inventory_sha256": input_inventory_sha, "created_at_utc": datetime.now(UTC).isoformat(), "counts": {"nodes": counts["nodes"], "segments": counts["segments"], "arcs": counts["arcs"], "source_candidates": counts["candidates"], "excluded_candidates": excluded, "unknown_candidates": unknown, "unsupported_restrictions": unsupported, "unresolved_relation_members": unresolved}, "checks": {"raw_osm_hash": "pass" if not synthetic else "not_applicable", "frozen_graph_hashes": "pass", "source_inventory_hash": "pass", "schemas": "pass", "source_geometry_and_costs": "pass", "directed_arc_membership": "pass", "gpkg_hash": "pass", "manual_gis_review": "not_run", "station_entrance_verification": "not_run", "coverage": coverage["readiness"]}, "limitations": coverage["limitations"], "construction_seconds": round(time.monotonic() - started, 3), "pipeline_mode": "synthetic_fixture" if synthetic else "accepted_frozen_graph_reuse"}
        write_json(stage / "qa.json", report_payload)
        (stage / "notices.txt").write_text(source_license_text(synthetic=synthetic), encoding="utf-8", newline="\n")
        file_keys = {"nodes": ("nodes.json", counts["nodes"]), "segments": ("segments.json", counts["segments"]), "arcs": ("arcs.json", counts["arcs"]), "inventory": ("inventory.json", 1), "qa": ("qa.json", 1), "gis": ("routing.gpkg", counts["nodes"] + counts["arcs"] + counts["candidates"]), "notices": ("notices.txt", 1)}
        files = {name: file_descriptor(stage / filename, records) for name, (filename, records) in file_keys.items()}
        bounded_package(stage, files)
        manifest = {"schema_version": "flm-package-1", "release_id": release_id, "graph_id": graph_id, "status": "complete_experimental", "identity": identity, "coverage": coverage, "diagnostics": diagnostics, "crs": "EPSG:4326", "coordinate_order": "longitude_latitude", "length_unit": "international_foot", "time_unit": "second", "travel_profile": "general_pedestrian", "wheelchair_accessibility": "not_evaluated", "compatible_app_versions": ["0.1.0"], "files": files, "counts": {"nodes": counts["nodes"], "segments": counts["segments"], "arcs": counts["arcs"]}, "created_at": datetime.now(UTC).isoformat(), "evidence": [{"check": outcome, "outcome": "pass", "detail": "Package producer validation"} for outcome in outcomes] + [{"check": "manual_gis_review", "outcome": "not_run", "detail": "No package-specific manual GIS review was performed."}, {"check": "verified_station_entrance", "outcome": "not_run", "detail": "Source node is diagnostic and is not a verified entrance."}]}
        schema_check(manifest, "manifest")
        write_json(stage / "manifest.json", manifest)
        validate_release(stage / "manifest.json")
        need(not final.exists(), f"release ID already exists: {release_id}")
        os.replace(stage, final)
        return final, manifest
    except Exception as exc:
        # No manifest is written before all content and schemas pass. Preserve failed stage logs for inspection.
        (stage / "failure.json").write_text(json.dumps({"status": "failed", "error": str(exc), "created_at_utc": datetime.now(UTC).isoformat()}, indent=2) + "\n", encoding="utf-8")
        raise


def validate_release(manifest_path):
    original_manifest_path = Path(manifest_path)
    need(original_manifest_path.name in {"manifest.json", "candidate-manifest.json"} and not original_manifest_path.is_symlink(), "manifest must be a local package manifest")
    manifest_path = original_manifest_path.resolve(strict=True)
    root = manifest_path.parent.resolve(strict=True)
    manifest = read_json(manifest_path, MAX["manifest"]); schema_check(manifest, "manifest")
    if manifest["identity"]["length_model"] == "wgs84_geodesic_international_ft":
        need(manifest["coverage"]["readiness"] == "not_established", "OSM graph cannot declare complete coverage in package v1")
        need(manifest["status"] == "complete_experimental" and manifest["diagnostics"]["analytical_promotion"] == "blocked_experimental", "regional package promotion must remain blocked")
    else:
        need(manifest["coverage"]["readiness"] == "synthetic_closed" and all(source["kind"] == "synthetic" for source in read_json(root / manifest["files"]["inventory"]["path"])["sources"]), "declared synthetic lengths require synthetic-only source inventory")
    need(bbox_ok(manifest["coverage"]["core_bbox"]) and bbox_ok(manifest["coverage"]["extract_bbox"]), "invalid package bbox")
    core, extract = manifest["coverage"]["core_bbox"], manifest["coverage"]["extract_bbox"]
    need(extract[0] <= core[0] <= core[2] <= extract[2] and extract[1] <= core[1] <= core[3] <= extract[3], "core bbox outside extraction bbox")
    total = 0; inventory = None; qa = None
    need(len({item["path"] for item in manifest["files"].values()}) == len(manifest["files"]), "file descriptors reuse paths")
    for key, desc in manifest["files"].items():
        rel = Path(desc["path"])
        need(not rel.is_absolute() and len(rel.parts) == 1 and rel.name == desc["path"] and rel.name not in {".", ".."}, f"unsafe path: {desc['path']}")
        path = root / rel
        need(not path.is_symlink() and path.resolve(strict=True).parent == root, f"file escapes release: {rel}")
        need(path.stat().st_size == desc["bytes"] and sha(path) == desc["sha256"], f"file size/hash mismatch: {rel}")
        total += path.stat().st_size
        if key in {"nodes", "segments", "arcs", "inventory", "qa"}:
            payload = read_json(path)
            schema_name = {"nodes":"nodes", "segments":"segments", "arcs":"arcs", "inventory":"inventory", "qa":None}[key]
            if schema_name: schema_check(payload, schema_name)
            if key != "inventory":
                need(payload["release_id"] == manifest["release_id"] and payload["graph_id"] == manifest["graph_id"], f"release/graph binding mismatch in {key}")
                need(desc["records"] == manifest["counts"][key] if key in {"nodes", "segments", "arcs"} else desc["records"] == 1, f"record count mismatch: {key}")
            else:
                need(sha(path) == manifest["identity"]["source_inventory_sha256"], "inventory identity mismatch")
                inventory = payload
            if key == "qa": qa = payload
        elif key == "gis":
            # GDAL validates the container and layer existence; detailed feature reconciliation is done at build time.
            import pyogrio
            layers = set(pyogrio.list_layers(path)[:, 0])
            need({"routing_nodes", "routing_arcs", "candidate_audit"} <= layers, "routing GeoPackage lacks expected layers")
        elif key == "notices":
            text = path.read_text(encoding="utf-8")
            if manifest["identity"]["length_model"] == "wgs84_geodesic_international_ft":
                need("Open Database License 1.0" in text and "OpenStreetMap contributors" in text, "attribution/license notice missing")
            else:
                need("Synthetic fixture data only" in text, "synthetic fixture notice mismatch")
    need(total <= MAX["package"], "total release size cap exceeded")
    need(total + manifest_path.stat().st_size <= MAX["package"], "total release size cap including manifest exceeded")
    browser_size = sum(manifest["files"][x]["bytes"] for x in ("nodes", "segments", "arcs", "inventory"))
    need(browser_size <= MAX["browser_json"], "browser JSON cap exceeded")
    for key in ("nodes", "segments", "arcs", "inventory"):
        need(manifest["files"][key]["bytes"] <= MAX["json"], f"per-file JSON cap exceeded: {key}")
    need(manifest["counts"] == {k: manifest["files"][k]["records"] for k in ("nodes", "segments", "arcs")}, "manifest counts/descriptors mismatch")
    need(inventory is not None and qa is not None, "inventory or QA record missing")
    need(qa.get("release_id") == manifest["release_id"] and qa.get("graph_id") == manifest["graph_id"] and qa.get("status") == "complete_experimental", "QA identity mismatch")
    need(sha(root / manifest["files"]["inventory"]["path"]) == manifest["identity"]["source_inventory_sha256"], "inventory file does not match graph identity")
    source = inventory["sources"][0]
    need(qa["counts"]["nodes"] == manifest["counts"]["nodes"] and qa["counts"]["segments"] == manifest["counts"]["segments"] and qa["counts"]["arcs"] == manifest["counts"]["arcs"], "QA counts do not match manifest")
    if manifest["identity"]["length_model"] == "wgs84_geodesic_international_ft":
        need(source["kind"] == "osm" and source["sha256"] == qa["producer_source_sha256"], "inventory source does not match frozen graph source")
        need(qa["source_inventory_sha256"] == manifest["identity"]["source_inventory_sha256"], "QA inventory binding mismatch")
    validate_graph_payloads(root, manifest)
    import pyogrio
    gpkg = root / manifest["files"]["gis"]["path"]
    for layer, expected in (("routing_nodes", manifest["counts"]["nodes"]), ("routing_arcs", manifest["counts"]["arcs"]), ("candidate_audit", qa["counts"]["source_candidates"])):
        info = pyogrio.read_info(gpkg, layer=layer)
        need(info["features"] == expected and info["crs"] == "EPSG:4326", f"GIS layer count/CRS mismatch: {layer}")
    need(manifest["diagnostics"]["analytical_promotion"] == "blocked_experimental", "unexpected promotion state")
    return {"status":"pass", "release_id":manifest["release_id"], "graph_id":manifest["graph_id"], "bytes":total, "counts":manifest["counts"]}


def load_handoff(path):
    return read_json(Path(path), 4 * 1024 * 1024)


def _prepare_child(args):
    candidate, manifest = package(args.graph, args.inventory, args.handoff, args.release_id, args.worker_output)
    qa = read_json(candidate / manifest["files"]["qa"]["path"], MAX["json"])
    write_json(args.result, {"candidate": candidate.relative_to(ROOT).as_posix(), "release_id": manifest["release_id"], "graph_id": manifest["graph_id"], "manifest_sha256": sha(candidate / "manifest.json"), "packager_code_sha256": qa["packager_code_sha256"]})


def prepare(handoff_path, output_root, release_id=None):
    from flm_pipeline.cli import _supervise

    handoff_path = Path(handoff_path).resolve(strict=True); handoff = load_handoff(handoff_path)
    graph = ROOT / handoff["graph_directory"]
    source_inventory = ROOT / handoff["inventory"]
    rid = release_id or f"denver-union-policy-03-{handoff['graph_run_id']}"
    final_root = Path(output_root).resolve()
    allowed_final = (ROOT / "data/generated/prototype/network-packages").resolve()
    need(final_root.is_relative_to(allowed_final), "release output must remain under ignored data/generated/prototype/network-packages")
    final = final_root / rid
    need(not final.exists(), f"release ID already exists: {rid}")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    supervisor_stage = ROOT / "data/staging/prototype/network-package-supervision" / run_id
    worker_root = ROOT / "data/staging/prototype/network-package-candidates" / run_id
    supervisor_stage.mkdir(parents=True); worker_root.mkdir(parents=True)
    result_path = supervisor_stage / "candidate.json"
    command = [sys.executable, str(Path(__file__).resolve()), "_prepare-worker", "--handoff", str(handoff_path), "--graph", str(graph), "--inventory", str(source_inventory), "--release-id", rid, "--worker-output", str(worker_root), "--result", str(result_path)]
    supervision = _supervise(command, ROOT, supervisor_stage / "worker.log", 1200, 4 * 1024**3)
    if supervision["exit_code"] != 0 or supervision.get("failure_reason") or not supervision.get("child_cleanup_complete", False) or not result_path.exists():
        write_json(supervisor_stage / "failure.json", {"status": "fail", "supervision": supervision, "release_id": rid})
        raise PackageError(f"package worker failed or exceeded resource limits; diagnostics: {supervisor_stage.relative_to(ROOT)}")
    worker_result = read_json(result_path, 1024 * 1024)
    candidate = (ROOT / worker_result["candidate"]).resolve(strict=True)
    need(candidate.is_relative_to(worker_root.resolve()), "worker candidate escaped its staging root")
    manifest_path = candidate / "manifest.json"
    manifest = read_json(manifest_path, MAX["manifest"])
    schema_check(manifest, "manifest")
    need(worker_result["release_id"] == rid and worker_result["graph_id"] == manifest["graph_id"] and worker_result["manifest_sha256"] == sha(manifest_path) and worker_result["packager_code_sha256"] == PACKAGER_CODE_SHA256, "validated worker output changed before promotion")
    qa = read_json(candidate / manifest["files"]["qa"]["path"], MAX["json"])
    need(qa["packager_code_sha256"] == worker_result["packager_code_sha256"], "packager implementation identity changed before promotion")
    final_root.mkdir(parents=True, exist_ok=True)
    need(not final.exists(), f"release ID already exists: {rid}")
    os.replace(candidate, final)
    write_json(supervisor_stage / "completion.json", {"status": "pass", "release_directory": final.relative_to(ROOT).as_posix(), "release_id": rid, "graph_id": manifest["graph_id"], "manifest_sha256": worker_result["manifest_sha256"], "packager_code_sha256": worker_result["packager_code_sha256"], "validation": "complete_package_validation_before_atomic_promotion", "supervision": supervision})
    return final, manifest


def build_synthetic(release_id, output_root):
    """Make one real local package from the hand-authored F01 example."""
    import geopandas as gpd
    from shapely.geometry import LineString, Point

    need(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,159}", release_id) is not None and "/" not in release_id and ".." not in release_id, "invalid release ID")
    output_root = Path(output_root).resolve()
    need(not (output_root / release_id).exists(), f"release ID already exists: {release_id}")
    need(not (output_root / "_expected-results" / f"{release_id}.json").exists(), f"expected result already exists: {release_id}")
    fixture = ROOT / "pipeline/fixtures/network-package-v1"
    example = read_json(fixture / "manifest.example.json", MAX["manifest"])
    nodes_payload = read_json(fixture / "nodes.json", MAX["json"])["nodes"]
    segments_payload = read_json(fixture / "segments.json", MAX["json"])["segments"]
    arcs_payload = read_json(fixture / "arcs.json", MAX["json"])["arcs"]
    work = ROOT / "data/staging/prototype/package-synthetic-input" / uuid.uuid4().hex[:8]
    work.mkdir(parents=True)
    try:
        nodes = [{"node_id": r["node_id"], "lon": r["coordinate"][0], "lat": r["coordinate"][1]} for r in nodes_payload]
        segments = [{**r, "eligibility": "include", "same_endpoint_id": False, "reason_codes": [], "warnings": [], "routing_ready": True} for r in segments_payload]
        by_id = {r["candidate_id"]: r for r in segments_payload}
        arcs = []
        for r in arcs_payload:
            seg = by_id[r["candidate_id"]]
            coords = list(reversed(seg["coordinates"])) if r["direction"] == "reverse" else seg["coordinates"]
            arcs.append({**r, "way_id": seg["way_id"], "sequence": seg["sequence"], "coordinates": coords, "length_ft": seg["length_ft"], "base_seconds": seg["base_seconds"]})
        for name, records in (("nodes.jsonl", nodes), ("segments.jsonl", segments), ("arcs.jsonl", arcs)):
            with (work / name).open("w", encoding="utf-8", newline="\n") as stream:
                for row in records: stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        (work / "relations-audit.jsonl").write_text("", encoding="utf-8")
        node_frame = gpd.GeoDataFrame({"node_id":[r["node_id"] for r in nodes],"lon":[r["lon"] for r in nodes],"lat":[r["lat"] for r in nodes]}, geometry=[Point(r["lon"], r["lat"]) for r in nodes], crs="EPSG:4326")
        arc_frame = gpd.GeoDataFrame({key:[r[key] for r in arcs] for key in ("edge_id","candidate_id","way_id","from_node_id","to_node_id","direction","sequence","length_ft","base_seconds")}, geometry=[LineString(r["coordinates"]) for r in arcs], crs="EPSG:4326")
        candidate_frame = gpd.GeoDataFrame({key:[r[key] for r in segments] for key in ("candidate_id","way_id","from_node_id","to_node_id","direction","eligibility","sequence","length_ft")}, geometry=[LineString(r["coordinates"]) for r in segments], crs="EPSG:4326")
        gpkg = work / "routing.gpkg"
        node_frame.to_file(gpkg, layer="routing_nodes", driver="GPKG", index=False)
        arc_frame.to_file(gpkg, layer="routing_arcs", driver="GPKG", index=False, mode="a")
        candidate_frame.to_file(gpkg, layer="candidate_audit", driver="GPKG", index=False, mode="a")
        status = {"report_version":"experimental-routing-graph-1", "status":"experimental_graph_complete", "synthetic_fixture":True, "checks":{"worker_exit_zero":True,"structural_validation":True,"gpkg_all_records_reopened":True,"input_hashes_verified_before_after":True}, "counts":{"nodes":3,"candidates":2,"candidates_by_eligibility":{"include":2,"exclude":0,"unknown":0},"directed_arcs":3}, "relations":{"unsupported":0,"unresolved_members":0}, "policy":{"rule_version":example["identity"]["rule_version"],"scenario_id":example["identity"]["scenario_id"],"authority_sha256":example["identity"]["rule_sha256"],"config_sha256":example["identity"]["config_sha256"],"travel_profile":"general_pedestrian"}, "identity":{"code_sha256":example["identity"]["code_sha256"]}, "coverage":{"core_bbox":example["coverage"]["core_bbox"],"extract_bbox":example["coverage"]["extract_bbox"]}, "limitations":["Synthetic metric lengths are declared and do not match illustrative coordinates."], "output_files":{"routing.gpkg":{"bytes":gpkg.stat().st_size,"sha256":sha(gpkg)}}}
        write_json(work / "run-report.json", status)
        run_id = uuid.uuid4().hex[:8]
        worker_root = ROOT / "data/staging/prototype/network-package-candidates" / ("synthetic-" + run_id)
        worker_root.mkdir(parents=True)
        final_root = Path(output_root); final_root.mkdir(parents=True, exist_ok=True)
        # Copy the synthetic input set to an isolated run directory; package() treats it as frozen input.
        candidate_graph = worker_root / "graph-input"; shutil.copytree(work, candidate_graph)
        result, manifest = package(candidate_graph, fixture / "inventory.json", None, release_id, worker_root / "candidate", synthetic=True)
        final = final_root / release_id
        need(not final.exists(), f"release ID already exists: {release_id}")
        os.replace(result, final)
        bind_expected_result(final, final_root)
        return final, manifest
    finally:
        if work.is_relative_to(ROOT / "data/staging/prototype/package-synthetic-input"):
            shutil.rmtree(work, ignore_errors=True)


def bind_expected_result(release_dir, output_root):
    """Bind the literal synthetic expectation to this generated package manifest."""
    manifest_path = release_dir / "manifest.json"
    manifest = read_json(manifest_path, MAX["manifest"])
    expected = read_json(ROOT / "pipeline/fixtures/network-package-v1/expected-result.json", MAX["manifest"])
    expected.update({
        "release_id": manifest["release_id"],
        "graph_id": manifest["graph_id"],
        "manifest_sha256": sha(manifest_path),
    })
    schema_check(expected, "result")
    need(expected["graph_id"] == manifest["graph_id"] and expected["release_id"] == manifest["release_id"], "synthetic expected result does not match generated release")
    destination = Path(output_root) / "_expected-results" / f"{manifest['release_id']}.json"
    need(not destination.exists(), f"expected result already exists: {destination.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    write_json(temporary, expected)
    os.replace(temporary, destination)
    return destination


def _validate_child(args):
    result = validate_release(args.manifest)
    write_json(args.result, result)


def validate_supervised(manifest_path):
    from flm_pipeline.cli import _supervise

    original = Path(manifest_path)
    need(not original.is_symlink(), "manifest must not be a symlink")
    manifest = original.resolve(strict=True)
    release_root = (ROOT / "data/generated/prototype/network-packages").resolve(strict=True)
    need(manifest.is_relative_to(release_root), "manifest must be under the ignored local package release root")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    stage = ROOT / "data/staging/prototype/network-package-validation" / run_id
    stage.mkdir(parents=True)
    result_path = stage / "result.json"
    command = [sys.executable, str(Path(__file__).resolve()), "_validate-worker", "--manifest", str(manifest), "--result", str(result_path)]
    supervision = _supervise(command, ROOT, stage / "worker.log", 1200, 4 * 1024**3)
    if supervision["exit_code"] != 0 or supervision.get("failure_reason") or not supervision.get("child_cleanup_complete", False) or not result_path.exists():
        write_json(stage / "failure.json", {"status": "fail", "supervision": supervision, "manifest": manifest.relative_to(ROOT).as_posix()})
        raise PackageError(f"package validation failed or exceeded resource limits; diagnostics: {stage.relative_to(ROOT)}")
    result = read_json(result_path, 1024 * 1024)
    write_json(stage / "completion.json", {"status": "pass", "manifest": manifest.relative_to(ROOT).as_posix(), "validation": result, "supervision": supervision})
    return {**result, "supervision": supervision}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("prepare-release", help="verify accepted handoff and package its frozen graph")
    p.add_argument("--handoff", type=Path, default=APPROVED); p.add_argument("--output-root", type=Path, default=ROOT / "data/generated/prototype/network-packages"); p.add_argument("--release-id")
    v = subs.add_parser("validate-package", help="verify all package files, schema, hashes, paths and GIS layers")
    v.add_argument("--manifest", type=Path, required=True)
    s = subs.add_parser("build-synthetic", help="build the local F01 package from literal fixture records")
    s.add_argument("--release-id", default="synthetic-f01-v1"); s.add_argument("--output-root", type=Path, default=ROOT / "data/generated/prototype/network-packages")
    w = subs.add_parser("_prepare-worker", help=argparse.SUPPRESS)
    w.add_argument("--handoff", type=Path, required=True); w.add_argument("--graph", type=Path, required=True); w.add_argument("--inventory", type=Path, required=True); w.add_argument("--release-id", required=True); w.add_argument("--worker-output", type=Path, required=True); w.add_argument("--result", type=Path, required=True)
    vw = subs.add_parser("_validate-worker", help=argparse.SUPPRESS)
    vw.add_argument("--manifest", type=Path, required=True); vw.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "_prepare-worker":
            _prepare_child(args)
        elif args.command == "_validate-worker":
            _validate_child(args)
        elif args.command == "build-synthetic":
            final, manifest = build_synthetic(args.release_id, args.output_root)
            expected_result = Path(args.output_root).resolve() / "_expected-results" / f"{manifest['release_id']}.json"
            print(json.dumps({"status":"pass", "release_directory":final.relative_to(ROOT).as_posix(), "release_id":manifest["release_id"], "graph_id":manifest["graph_id"], "counts":manifest["counts"], "expected_result":expected_result.relative_to(ROOT).as_posix(), "expected_result_sha256":sha(expected_result)}, indent=2))
        elif args.command == "prepare-release":
            final, manifest = prepare(args.handoff, args.output_root, args.release_id)
            print(json.dumps({"status":"pass", "release_directory":final.relative_to(ROOT).as_posix(), "release_id":manifest["release_id"], "graph_id":manifest["graph_id"], "counts":manifest["counts"]}, indent=2))
        else:
            print(json.dumps(validate_supervised(args.manifest), indent=2))
    except Exception as exc:
        print(f"package error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

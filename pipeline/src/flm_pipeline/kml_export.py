"""Build a source-preserving Google Earth review package from a validated export."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import html
import json
import math
import os
from pathlib import Path
import sqlite3
import struct
import time
import uuid
from xml.sax.saxutils import escape, quoteattr
import zipfile
import zlib

import pyogrio

from .code_identity import code_identity
from .config import ConfigError, PipelineConfig, load_config
from .extractor import sha256_file
from .gpkg_export import ExportFailure, _validate_extraction
from .runtime import environment_errors, runtime_versions


INSPECTION_VERSION = "earth-inspection-1"
MAX_PLACEMARKS = 10_000
MAX_VERTICES = 250_000
MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
MAX_DIAGNOSTIC_MARKERS = 500
_CHUNK_SIZE = 1_000


class InspectionFailure(RuntimeError):
    """Invalid package inputs or failed inspection-package validation."""


def _hash(path: Path) -> str:
    return sha256_file(path)


def _xml(value: object) -> str:
    return escape(str(value), {"\"": "&quot;", "'": "&apos;"})


def _cdata(value: str) -> str:
    return "<![CDATA[" + value.replace("]]>", "]]]]><![CDATA[>") + "]] >".replace(" ", "")


def _safe_xml_id(prefix: str, source_id: str) -> str:
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _tags_table(tags: dict[str, str]) -> str:
    rows = "".join(f"<tr><th>{html.escape(key)}</th><td>{html.escape(value)}</td></tr>" for key, value in sorted(tags.items()))
    return f"<table><tbody>{rows}</tbody></table>"


def _feature_description(title: str, rows: list[tuple[str, object]], tags: dict[str, str], technical: list[tuple[str, object]]) -> str:
    """Keep review fields first and exact source evidence in a labeled secondary section."""
    def table(values: list[tuple[str, object]]) -> str:
        return "<table>" + "".join(f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(value))}</td></tr>" for label, value in values) + "</table>"

    labels = {"highway": "Road/path type", "name": "Name", "bridge": "Bridge", "tunnel": "Tunnel", "layer": "Source layer", "barrier": "Barrier", "crossing": "Crossing", "sidewalk": "Sidewalk", "foot": "Foot access tag"}
    key_tags = [(label, tags[key] if tags[key] else "(empty value)") for key, label in labels.items() if key in tags]
    summary = f"<h3>{html.escape(title)}</h3>" + table(rows)
    if key_tags:
        summary += "<h4>Key source tags</h4>" + table(key_tags)
    return summary + "<hr/><h4>Technical details</h4>" + table(technical) + "<h4>All raw source tags</h4>" + (_tags_table(tags) if tags else "<p>No source tags.</p>")


def _placemark(
    *,
    xml_id: str,
    name: str,
    description: str,
    geometry_xml: str,
    fields: dict[str, object],
    style: str | None = None,
) -> str:
    data = "".join(
        f"<Data name={quoteattr(key)}><value>{_xml(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) if not isinstance(value, str) else value)}</value></Data>"
        for key, value in fields.items()
    )
    style_xml = f"<styleUrl>#{style}</styleUrl>" if style else ""
    return (
        f"<Placemark id={quoteattr(xml_id)}><name>{_xml(name)}</name>"
        f"<description>{_cdata(description)}</description>{style_xml}"
        '<Style><BalloonStyle><text>$[description]</text></BalloonStyle></Style>'
        f"<ExtendedData>{data}</ExtendedData>{geometry_xml}</Placemark>\n"
    )


def _point_xml(lon: float, lat: float) -> str:
    return f"<Point><altitudeMode>clampToGround</altitudeMode><coordinates>{lon:.15g},{lat:.15g},0</coordinates></Point>"


def _line_xml(coordinates: list[tuple[float, float]]) -> str:
    if len(coordinates) < 2:
        raise InspectionFailure("A line feature has fewer than two coordinates")
    points = " ".join(f"{lon:.15g},{lat:.15g},0" for lon, lat in coordinates)
    return f"<LineString><tessellate>0</tessellate><altitudeMode>clampToGround</altitudeMode><coordinates>{points}</coordinates></LineString>"


def _bounds(box: list[float]) -> list[list[float]]:
    west, south, east, north = box
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


def _polygon_xml(coordinates: list[list[float]]) -> str:
    ring = " ".join(f"{x:.15g},{y:.15g},0" for x, y in coordinates)
    return f"<Polygon><tessellate>0</tessellate><altitudeMode>clampToGround</altitudeMode><outerBoundaryIs><LinearRing><coordinates>{ring}</coordinates></LinearRing></outerBoundaryIs></Polygon>"


def _png_icon(kind: str, rgba: tuple[int, int, int, int]) -> bytes:
    """Return a tiny local PNG marker; icons never load from a network URL."""
    width = height = 32
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            dx, dy = x - 15.5, y - 15.5
            if kind == "circle":
                inside = dx * dx + dy * dy <= 13.5 * 13.5
            elif kind == "square":
                inside = abs(dx) <= 12.5 and abs(dy) <= 12.5
            else:
                inside = abs(dx) + abs(dy) <= 18
            edge = inside and not (
                abs(dx) + abs(dy) <= 15 if kind == "diamond"
                else dx * dx + dy * dy <= 10.5 * 10.5 if kind == "circle"
                else abs(dx) <= 9.5 and abs(dy) <= 9.5
            )
            color = (35, 35, 35, 255) if edge else rgba if inside else (0, 0, 0, 0)
            row.extend(color)
        rows.append(bytes(row))

    def chunk(name: bytes, data: bytes) -> bytes:
        body = name + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    image_data = zlib.compress(b"".join(rows), 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + chunk(b"IDAT", image_data) + chunk(b"IEND", b"")


def _write_icons(candidate: Path) -> dict[str, str]:
    icons = candidate / "icons"
    icons.mkdir()
    files = {
        "source-node.png": _png_icon("circle", (143, 45, 140, 255)),
        "review-case.png": _png_icon("square", (178, 114, 0, 255)),
        "diagnostic.png": _png_icon("diamond", (64, 64, 220, 255)),
    }
    for name, content in files.items():
        (icons / name).write_bytes(content)
    return {key: f"icons/{name}" for key, name in (("node", "source-node.png"), ("case", "review-case.png"), ("diagnostic", "diagnostic.png"))}


def _folders_start(stream: object, name: str, visible: bool) -> None:
    stream.write(f"<Folder><name>{_xml(name)}</name><visibility>{1 if visible else 0}</visibility>\n")


def _read_layer(gpkg: Path, layer: str, expected_count: int):
    for offset in range(0, expected_count, _CHUNK_SIZE):
        frame = pyogrio.read_dataframe(gpkg, layer=layer, skip_features=offset, max_features=min(_CHUNK_SIZE, expected_count - offset))
        yield from (row for _, row in frame.iterrows())


def _diagnostic_markers(
    extraction_dir: Path,
    metadata: dict[str, object],
    report: dict[str, object],
    lookup: sqlite3.Connection,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    diagnostics = {**metadata.get("diagnostics", {}), **report["diagnostics"]}
    candidates: list[dict[str, object]] = []
    considered = without_location = capped = 0

    def add(kind: str, source_id: str, lon: float | None, lat: float | None, fields: dict[str, object], description: str) -> None:
        nonlocal considered, without_location, capped
        considered += 1
        if lon is None or lat is None:
            without_location += 1
            return
        if len(candidates) >= MAX_DIAGNOSTIC_MARKERS:
            capped += 1
            return
        candidates.append({"kind": kind, "source_id": source_id, "lon": lon, "lat": lat, "fields": fields, "description": description})

    for example in diagnostics.get("zero_length_segment_examples", []):
        row = lookup.execute("SELECT lon, lat FROM nodes WHERE osm_id = ?", (str(example["from_node_id"]),)).fetchone()
        add("zero_length_segment", str(example["segment_id"]), *(row or (None, None)), {**example, "diagnostic": "zero_length_segment"}, "Zero-length source segment. This distinct marker is a display aid; the original source segment is retained.")
    for example in diagnostics.get("repeated_way_node_reference_examples", []):
        row = lookup.execute("SELECT lon, lat FROM nodes WHERE osm_id = ?", (str(example["node_id"]),)).fetchone()
        add("repeated_way_node_reference", f"{example['way_id']}:{example['sequence']}", *(row or (None, None)), {**example, "diagnostic": "repeated_way_node_reference"}, "A way references this node more than once. Source order is retained; this marker does not repair geometry.")
    for layer_name, table_name in (("source_ways", "ways"), ("source_segments", "segments")):
        summary = diagnostics.get("duplicate_geometries", {}).get(layer_name, {})
        for example in summary.get("examples", []):
            duplicate_id = str(example["duplicate_id"])
            row = lookup.execute(f"SELECT lon, lat FROM {table_name} WHERE object_id = ?", (duplicate_id,)).fetchone()
            add("duplicate_geometry", duplicate_id, *(row or (None, None)), {**example, "geometry_layer": layer_name, "diagnostic": "duplicate_geometry"}, "This feature has a coordinate sequence reported as an exact duplicate (direction reversal counts as equivalent). No feature is removed.")
    for example in diagnostics.get("degenerate_geometry_examples", []):
        layer_name, source_id = str(example["layer"]), str(example["feature_id"])
        table_name = "ways" if layer_name == "source_ways" else "segments"
        row = lookup.execute(f"SELECT lon, lat FROM {table_name} WHERE object_id = ?", (source_id,)).fetchone()
        add("degenerate_geometry", source_id, *(row or (None, None)), {**example, "diagnostic": "degenerate_geometry"}, "The source geometry is reported as degenerate by the GeoPackage export. Geometry is retained without repair.")

    unresolved_examples = diagnostics.get("unresolved_relation_member_examples", [])
    relation_ids = {str(example["relation_id"]) for example in unresolved_examples}
    relation_records: dict[str, dict[str, object]] = {}
    if relation_ids:
        with (extraction_dir / "relations.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                relation_id = str(record.get("osm_id"))
                if relation_id in relation_ids:
                    relation_records[relation_id] = record
                    if len(relation_records) == len(relation_ids):
                        break
    for example in unresolved_examples:
        relation_id = str(example["relation_id"])
        record = relation_records.get(relation_id)
        if record is None:
            continue
        context = None
        for member in record["members"]:
            if not member.get("resolved"):
                continue
            if member["type"] == "node":
                context = lookup.execute("SELECT lon, lat FROM nodes WHERE osm_id = ?", (str(member["ref"]),)).fetchone()
            elif member["type"] == "way":
                context = lookup.execute("SELECT lon, lat FROM ways WHERE object_id = ?", (str(member["ref"]),)).fetchone()
            if context:
                break
        add("unresolved_relation_member", f"{relation_id}:{example['member_index']}", *(context or (None, None)), {**example, "diagnostic": "unresolved_relation_member"}, "This relation member is unresolved in the selected source subset. The marker is placed at another resolved member when available; it has no invented relation geometry.")

    for row in lookup.execute("SELECT osm_id, lon, lat FROM nodes WHERE inside_extract = 0 ORDER BY osm_id LIMIT 20"):
        add("boundary_overhang", str(row[0]), float(row[1]), float(row[2]), {"osm_id": str(row[0]), "diagnostic": "boundary_overhang"}, "This source node lies outside the extract rectangle but is retained because it belongs to a selected complete way.")
    counts: dict[str, int] = {}
    for marker in candidates:
        counts[str(marker["kind"])] = counts.get(str(marker["kind"]), 0) + 1
    counts["omitted_without_spatial_context"] = without_location
    counts["omitted_at_marker_cap"] = capped
    counts["diagnostic_examples_considered"] = considered
    return candidates, counts


def _write_evidence(extraction: Path, gpkg: Path, segment_count: int, target: Path) -> tuple[dict[str, int], str]:
    counts: dict[str, int] = {}
    digest = hashlib.sha256()
    with target.open("wb") as stream:
        for filename, kind in (("nodes.jsonl", "node"), ("ways.jsonl", "way"), ("relations.jsonl", "relation")):
            count = 0
            for line in (extraction / filename).open("rb"):
                record = json.loads(line.decode("utf-8"))
                value = {"entity_type": kind, **record}
                raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
                stream.write(raw)
                digest.update(raw)
                count += 1
            counts[kind] = count
        count = 0
        for row in _read_layer(gpkg, "source_segments", segment_count):
            value = {key: (item.item() if hasattr(item, "item") else item) for key, item in row.items() if key != "geometry"}
            value["entity_type"] = "segment"
            value["coordinates_lon_lat"] = [[float(x), float(y)] for x, y, *_ in row.geometry.coords]
            raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            stream.write(raw)
            digest.update(raw)
            count += 1
        counts["segment"] = count
        stream.flush()
        os.fsync(stream.fileno())
    return counts, digest.hexdigest()


def _review_rows(kind: str, profile: str, metadata: dict[str, object], diagnostics: dict[str, object]) -> list[dict[str, str]]:
    west, south, east, north = metadata["coverage"]["extract_bbox"]
    core_west, core_south, core_east, core_north = metadata["coverage"]["core_bbox"]
    if kind == "synthetic":
        if metadata.get("status") == "empty":
            return [{"case_id": "SYN-E00", "place": "Empty selected network", "longitude": str(metadata["station_lonlat"][0]), "latitude": str(metadata["station_lonlat"][1]), "layers": "Package information; Coverage; Source nodes", "source_ids": "none", "expected_observation": "No highway ways were selected. This package is not a network and has no topology to inspect."}]
        if profile == "diagnostic":
            zero = diagnostics.get("zero_length_segment_examples", [])
            repeated = diagnostics.get("repeated_way_node_reference_examples", [])
            duplicate = diagnostics.get("duplicate_geometries", {}).get("source_segments", {}).get("examples", [])
            unresolved = metadata.get("diagnostics", {}).get("unresolved_relation_member_examples", [])
            return [
                {"case_id": "DIAG-01", "place": "Zero-length source segments", "longitude": str((west + east) / 2), "latitude": str((south + north) / 2), "layers": "Diagnostics; Source segments; Source nodes", "source_ids": "; ".join(str(row["segment_id"]) for row in zero) or "no zero-length examples in this fixture", "expected_observation": "Use the diagnostic display point to locate the retained source segment and confirm its endpoint IDs."},
                {"case_id": "DIAG-02", "place": "Repeated references", "longitude": str((west + east) / 2), "latitude": str((south + north) / 2), "layers": "Diagnostics; Source ways; Source nodes", "source_ids": "; ".join(f"way/{row['way_id']} node/{row['node_id']} sequence/{row['sequence']}" for row in repeated) or "no repeated reference examples in this fixture", "expected_observation": "Find the node and ordered way references; no source geometry is repaired."},
                {"case_id": "DIAG-03", "place": "Duplicate coordinate sequences", "longitude": str((west + east) / 2), "latitude": str((south + north) / 2), "layers": "Diagnostics; Source segments", "source_ids": "; ".join(str(row["duplicate_id"]) for row in duplicate) or "no duplicate segment examples in this fixture", "expected_observation": "Inspect both source feature IDs at the same location; neither is removed."},
                {"case_id": "DIAG-04", "place": "Unresolved relation members", "longitude": str((west + east) / 2), "latitude": str((south + north) / 2), "layers": "Diagnostics; Source ways; Source nodes", "source_ids": "; ".join(f"relation/{row['relation_id']} member/{row['member_index']} ref/{row['ref']}" for row in unresolved) or "no unresolved relation examples in this fixture", "expected_observation": "Confirm unresolved members remain in evidence; spatial markers use another resolved member when available."},
                {"case_id": "DIAG-05", "place": "Large ID and raw tag values", "longitude": str((west + east) / 2), "latitude": str((south + north) / 2), "layers": "Source ways; Source nodes", "source_ids": "way/9007199254740993", "expected_observation": "Confirm the large identifier, Unicode, escaped and empty tag values remain exact in the companion evidence."},
            ]
        return [
            {"case_id": "SYN-01", "place": "Synthetic geometric crossing", "longitude": "1.5", "latitude": "1.0", "layers": "Source segments; Source ways; Source nodes", "source_ids": "way/10/segment/1; way/13/segment/0; node/3", "expected_observation": "Lines cross geometrically without a shared node reference; node 3 belongs to way 10 but not the crossing way 13."},
            {"case_id": "SYN-02", "place": "Synthetic coincident nodes", "longitude": "1.0", "latitude": "1.0", "layers": "Source nodes; Source segments", "source_ids": "node/2; node/4; way/10/segment/0; way/11/segment/0", "expected_observation": "Nodes 2 and 4 share coordinates but retain separate source IDs and components."},
            {"case_id": "SYN-03", "place": "Synthetic bridge and tunnel", "longitude": "1.5", "latitude": "1.0", "layers": "Source ways; Source segments", "source_ids": "way/11; way/13", "expected_observation": "Bridge/tunnel tags survive; ground-clamped display has no measured vertical separation."},
            {"case_id": "SYN-04", "place": "Synthetic extract overhang", "longitude": "3.0", "latitude": "1.0", "layers": "Coverage; Source ways; Source nodes; Diagnostics", "source_ids": "way/10; node/8", "expected_observation": "A selected complete way retains its outside-boundary vertex."},
            {"case_id": "SYN-05", "place": "Synthetic tagged isolated node", "longitude": "0.25", "latitude": "1.75", "layers": "Source nodes; Diagnostics", "source_ids": "node/12", "expected_observation": "Standalone node retains source ID and barrier tags."},
        ]
    return [
        {"case_id": "DEN-01", "place": "Configured illustrative station vicinity", "longitude": str(metadata["station_lonlat"][0]), "latitude": str(metadata["station_lonlat"][1]), "layers": "Source ways; Source segments; Source nodes", "source_ids": "pending regional source review", "expected_observation": "Inspect nearby source objects; station access and permissions are not evaluated."},
        {"case_id": "DEN-02", "place": "Core coverage extent", "longitude": str((core_west + core_east) / 2), "latitude": str((core_south + core_north) / 2), "layers": "Coverage; Source ways; Source segments", "source_ids": "pending regional source review", "expected_observation": "Inspect representative source geometry and tags; record observed source IDs."},
        {"case_id": "DEN-03", "place": "West extract edge", "longitude": str(west), "latitude": str((south + north) / 2), "layers": "Coverage; Source ways; Source nodes", "source_ids": "pending regional source review", "expected_observation": "Inspect complete-way overhang and boundary selection; record actual source IDs."},
        {"case_id": "DEN-04", "place": "East extract edge", "longitude": str(east), "latitude": str((south + north) / 2), "layers": "Coverage; Source ways; Source nodes", "source_ids": "pending regional source review", "expected_observation": "Inspect complete-way overhang and boundary selection; record actual source IDs."},
        {"case_id": "DEN-05", "place": "South and north extract edges", "longitude": str((west + east) / 2), "latitude": str(south), "layers": "Coverage; Source ways; Source nodes", "source_ids": "pending regional source review", "expected_observation": "Inspect boundary cases and corner coverage; case coordinates are search aids."},
        {"case_id": "DEN-06", "place": "Diagnostic source objects", "longitude": str((west + east) / 2), "latitude": str((south + north) / 2), "layers": "Diagnostics; Source ways; Source nodes; Source relations", "source_ids": "pending regional source review", "expected_observation": "Find actual diagnostic feature IDs from the companion evidence/report; no defect is asserted."},
    ]


def _write_review_csv(path: Path, rows: list[dict[str, str]], manifest_id: str) -> None:
    fields = ["package_id", "case_id", "place", "longitude", "latitude", "layers", "expected_observation", "status", "reviewer", "date", "source_ids", "observation", "imagery_date", "screenshot_path", "follow_up"]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({"package_id": manifest_id, **row, "status": "not_run"})


def _write_document(candidate: Path, metadata: dict[str, object], export_report: dict[str, object], dataset_kind: str, package_id: str) -> dict[str, object]:
    gpkg = Path(export_report["output"]["absolute_path"])
    extraction_dir = Path(export_report["extraction_absolute_path"])
    layers = {"source_nodes": int(export_report["counts"]["source_nodes"]), "source_ways": int(export_report["counts"]["source_ways"]), "source_segments": int(export_report["counts"]["source_segments"]), "source_relations": int(export_report["counts"]["source_relations"]), "coverage": int(export_report["counts"]["coverage"])}
    vertices = 0
    for way in (json.loads(line) for line in (extraction_dir / "ways.jsonl").open(encoding="utf-8")):
        vertices += len(way["node_refs"])
    evidence_counts, evidence_digest = _write_evidence(extraction_dir, gpkg, layers["source_segments"], candidate / "source-evidence.jsonl")
    cases = _review_rows(dataset_kind, metadata.get("review_profile", "topology"), metadata, export_report["diagnostics"])
    _write_review_csv(candidate / "review-cases.csv", cases, package_id)
    _write_review_csv(candidate / "review-observations-template.csv", cases, package_id)

    lookup_path = candidate / "node-coordinates.sqlite"
    lookup = sqlite3.connect(lookup_path)
    lookup.execute("CREATE TABLE nodes (osm_id TEXT PRIMARY KEY, lon REAL NOT NULL, lat REAL NOT NULL, inside_extract INTEGER NOT NULL) WITHOUT ROWID")
    lookup.execute("CREATE TABLE incident_segments (node_id TEXT NOT NULL, segment_id TEXT NOT NULL, PRIMARY KEY(node_id, segment_id)) WITHOUT ROWID")
    lookup.execute("CREATE TABLE ways (object_id TEXT PRIMARY KEY, lon REAL NOT NULL, lat REAL NOT NULL) WITHOUT ROWID")
    lookup.execute("CREATE TABLE segments (object_id TEXT PRIMARY KEY, lon REAL NOT NULL, lat REAL NOT NULL) WITHOUT ROWID")
    for row in _read_layer(gpkg, "source_nodes", layers["source_nodes"]):
        lookup.execute("INSERT INTO nodes VALUES (?, ?, ?, ?)", (str(row["osm_id"]), float(row["lon"]), float(row["lat"]), int(row["inside_extract"])))
    for edge in _read_layer(gpkg, "source_segments", layers["source_segments"]):
        geometry = edge.geometry
        midpoint = geometry.interpolate(0.5, normalized=True)
        lookup.execute("INSERT INTO segments VALUES (?, ?, ?)", (str(edge["segment_id"]), float(midpoint.x), float(midpoint.y)))
        lookup.executemany("INSERT OR IGNORE INTO incident_segments VALUES (?, ?)", ((str(edge["from_node_id"]), str(edge["segment_id"])), (str(edge["to_node_id"]), str(edge["segment_id"]))))
    for way in _read_layer(gpkg, "source_ways", layers["source_ways"]):
        midpoint = way.geometry.interpolate(0.5, normalized=True)
        lookup.execute("INSERT INTO ways VALUES (?, ?, ?)", (str(way["osm_id"]), float(midpoint.x), float(midpoint.y)))
    lookup.commit()
    markers, diagnostic_counts = _diagnostic_markers(extraction_dir, metadata, export_report, lookup)
    placements = 1 + len(cases) + layers["source_nodes"] + layers["source_ways"] + layers["source_segments"] + layers["coverage"] + len(markers)
    vertices += 1 + layers["source_nodes"] + layers["source_segments"] * 2 + layers["coverage"] * 5 + len(cases) + len(markers)
    if placements > MAX_PLACEMARKS or vertices > MAX_VERTICES:
        lookup.close()
        raise InspectionFailure(f"Package exceeds first-trial limits: {placements} placemarks/{MAX_PLACEMARKS}, {vertices} vertices/{MAX_VERTICES}; no features were dropped")
    icon_paths = _write_icons(candidate)
    kml_path = candidate / "doc.kml"
    feature_counts = {"source_nodes": 0, "source_ways": 0, "source_segments": 0, "coverage": 0}
    with kml_path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>\n')
        stream.write(f"<name>{_xml(package_id)}</name><description>{_cdata(html.escape(f'{dataset_kind.upper()} inspection package. Source ID and raw tag review only; no pedestrian eligibility or routing.'))}</description>\n")
        stream.write('<Style id="source-line"><LineStyle><color>ff24a148</color><width>2</width></LineStyle></Style><Style id="source-way"><LineStyle><color>aa0072b2</color><width>1</width></LineStyle></Style>')
        for style, href, scale in (("source-node", icon_paths["node"], "0.75"), ("case", icon_paths["case"], "0.95"), ("diagnostic", icon_paths["diagnostic"], "0.95")):
            stream.write(f'<Style id="{style}"><IconStyle><scale>{scale}</scale><Icon><href>{_xml(href)}</href></Icon></IconStyle></Style>')
        stream.write("\n")
        _folders_start(stream, "Package information", True)
        info_lon, info_lat = metadata["station_lonlat"]
        source_sha = metadata.get("source", {}).get("sha256", "unavailable")
        package_status = "empty" if metadata["status"] == "empty" else "complete"
        source_info = metadata.get("source", {})
        inventory_info = source_info.get("inventory_evidence", {})
        info = {"package_id": package_id, "dataset_kind": dataset_kind, "status": package_status, "source_sha256": source_sha, "source_attribution": inventory_info.get("license_reference", "not present in source inventory"), "license_status": inventory_info.get("license_status", "unknown; no redistribution clearance"), "placemark_limit": MAX_PLACEMARKS, "vertex_limit": MAX_VERTICES, "byte_limit": MAX_PAYLOAD_BYTES, "coordinate_order": "longitude, latitude; WGS84", "known_limitations": "Source evidence only; ground-clamped display; visual crossings do not prove connectivity."}
        info_html = "<p>" + "</p><p>".join(f"<b>{html.escape(key)}</b>: {html.escape(str(value))}" for key, value in info.items()) + "</p>"
        stream.write(_placemark(xml_id=_safe_xml_id("package", package_id), name=f"Package information — {package_id}", description=info_html, geometry_xml=_point_xml(float(info_lon), float(info_lat)), fields=info))
        stream.write("</Folder>\n")
        _folders_start(stream, "Review cases", True)
        for row in cases:
            lon, lat = float(row["longitude"]), float(row["latitude"])
            stream.write(_placemark(xml_id=_safe_xml_id("case", row["case_id"]), name=f"{row['case_id']} — {row['place']}", description=f"<p>Package ID: {html.escape(package_id)}</p><p>{html.escape(row['expected_observation'])}</p><p>Source IDs: {html.escape(row.get('source_ids', ''))}</p>", geometry_xml=_point_xml(lon, lat), fields={**row, "package_id": package_id}, style="case"))
        stream.write("</Folder>\n")
        _folders_start(stream, "Coverage", True)
        for kind, key in (("core", "core_bbox"), ("extract", "extract_bbox"), ("expanded_comparison", "expanded_comparison_bbox")):
            box = metadata["coverage"][key]
            note = "Planned comparison extent; no expanded extraction demonstrated." if kind == "expanded_comparison" else f"Configured {kind} extent. This outline is not evidence of complete route coverage."
            visibility = "<visibility>0</visibility>" if kind == "expanded_comparison" else ""
            stream.write(f"<Placemark id={quoteattr(_safe_xml_id('coverage', kind))}><name>{_xml(f'Coverage — {kind}')}</name>{visibility}<description>{_cdata(html.escape(note))}</description><ExtendedData>")
            stream.write("".join(f"<Data name={quoteattr(field)}><value>{_xml(value if isinstance(value, str) else json.dumps(value, separators=(',', ':')))}</value></Data>" for field, value in {"coverage_kind": kind, "bbox_west_south_east_north": box, "crs": "EPSG:4326", "package_id": package_id}.items()))
            stream.write(f"</ExtendedData>{_polygon_xml(_bounds(box))}</Placemark>\n")
            feature_counts["coverage"] += 1
        stream.write("</Folder>\n")

        _folders_start(stream, "Source nodes", dataset_kind == "synthetic")
        node_count = layers["source_nodes"]
        for row in _read_layer(gpkg, "source_nodes", node_count):
            tags = json.loads(row["tags_json"])
            oid = str(row["osm_id"])
            incident = [item[0] for item in lookup.execute("SELECT segment_id FROM incident_segments WHERE node_id = ? ORDER BY segment_id", (oid,))]
            description = _feature_description(f"Node {oid}", [("Node ID", oid), ("Connected source segments", len(incident))], tags, [("Longitude", f"{row['lon']:.15g}"), ("Latitude", f"{row['lat']:.15g}"), ("Inside core area", "Yes" if row['inside_core'] else "No"), ("Inside extract area", "Yes" if row['inside_extract'] else "No"), ("Connected segment IDs", ', '.join(incident) if incident else "None"), ("Package ID", package_id)])
            fields = {"package_id": package_id, "osm_id": oid, "lon": float(row["lon"]), "lat": float(row["lat"]), "inside_core": int(row["inside_core"]), "inside_extract": int(row["inside_extract"]), "tags_json": row["tags_json"]}
            stream.write(_placemark(xml_id=_safe_xml_id("node", oid), name=f"node/{oid}", description=description, geometry_xml=_point_xml(float(row["lon"]), float(row["lat"])), fields=fields, style="source-node"))
            feature_counts["source_nodes"] += 1
        stream.write("</Folder>\n")

        _folders_start(stream, "Source segments", True)
        for row in _read_layer(gpkg, "source_segments", layers["source_segments"]):
            geometry = row.geometry
            coords = [(float(x), float(y)) for x, y, *_ in geometry.coords]
            tags = json.loads(row["tags_json"])
            sid = str(row["segment_id"])
            fields = {key: (value.item() if hasattr(value, "item") else value) for key, value in row.items() if key != "geometry"}
            fields["coordinate_order"] = "x longitude, y latitude, WGS84"
            summary_rows = [("Segment ID", sid), ("From node", str(row['from_node_id'])), ("To node", str(row['to_node_id'])), ("Length along Earth's surface", f"{float(row['length_geodesic_m']):,.2f} m")]
            if int(row['zero_length']):
                summary_rows.append(("Display", "Zero length: shown by a diagnostic point"))
            desc = _feature_description("Source segment", summary_rows, tags, [("Source way ID", str(row['way_id'])), ("Pair position in way (starts at 0)", int(row['sequence'])), ("Projected length (EPSG:26913 check)", f"{float(row['length_projected_m']):.9g} m"), ("Direction", "Source order only; walking direction is not evaluated"), ("Package ID", package_id)])
            fields["tags_json"] = row["tags_json"]
            fields["package_id"] = package_id
            stream.write(_placemark(xml_id=_safe_xml_id("segment", sid), name=sid, description=desc, geometry_xml=_line_xml(coords), fields=fields, style="source-line"))
            feature_counts["source_segments"] += 1
        stream.write("</Folder>\n")

        _folders_start(stream, "Source ways", False)
        for row in _read_layer(gpkg, "source_ways", layers["source_ways"]):
            coords = [(float(x), float(y)) for x, y, *_ in row.geometry.coords]
            tags = json.loads(row["tags_json"])
            oid = str(row["osm_id"])
            fields = {"package_id": package_id, "osm_id": oid, "node_refs_json": row["node_refs_json"], "node_count": int(row["node_count"]), "tags_json": row["tags_json"]}
            desc = _feature_description(f"Way {oid}", [("Way ID", oid), ("Number of source nodes", int(row['node_count']))], tags, [("Ordered node IDs", ', '.join(json.loads(row['node_refs_json']))), ("Package ID", package_id)])
            stream.write(_placemark(xml_id=_safe_xml_id("way", oid), name=f"way/{oid}", description=desc, geometry_xml=_line_xml(coords), fields=fields, style="source-way"))
            feature_counts["source_ways"] += 1
        stream.write("</Folder>\n")

        _folders_start(stream, "Diagnostics", False)
        for index, marker in enumerate(markers):
            fields = {"package_id": package_id, "diagnostic_kind": marker["kind"], "source_id": marker["source_id"], **marker["fields"]}
            description = _feature_description(str(marker["kind"]).replace("_", " ").capitalize(), [("Source feature", marker["source_id"]), ("What to check", marker["description"])], {}, [("Package ID", package_id)])
            xml_id = _safe_xml_id("diagnostic", f"{marker['kind']}:{marker['source_id']}:{index}")
            stream.write(_placemark(xml_id=xml_id, name=f"Diagnostic — {marker['kind']} — {marker['source_id']}", description=description, geometry_xml=_point_xml(float(marker["lon"]), float(marker["lat"])), fields=fields, style="diagnostic"))
        stream.write("</Folder>\n</Document></kml>\n")
        lookup.close()

    with zipfile.ZipFile(candidate / "source-network-inspection.kmz", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(kml_path, "doc.kml")
        for icon in sorted((candidate / "icons").glob("*.png")):
            archive.write(icon, f"icons/{icon.name}")
    kml_path.unlink()
    for icon in (candidate / "icons").glob("*"):
        icon.unlink()
    (candidate / "icons").rmdir()
    counts = {"source_nodes": feature_counts["source_nodes"], "source_ways": feature_counts["source_ways"], "source_segments": feature_counts["source_segments"], "source_relations": evidence_counts["relation"], "coverage": feature_counts["coverage"], "review_cases": len(cases), "source_evidence_records": sum(evidence_counts.values()), "diagnostic_markers": len(markers), "diagnostic_marker_counts": diagnostic_counts, "package_placemark_count": placements, "package_vertex_count": vertices}
    if any(counts[layer] != layers[layer] for layer in layers):
        raise InspectionFailure(f"KMZ feature counts do not reconcile to GeoPackage: {counts} versus {layers}")
    lookup.close()
    lookup_path.unlink(missing_ok=True)
    return {"counts": counts, "evidence_semantic_sha256": evidence_digest, "source_gpkg_counts": layers, "feature_vertex_count": vertices, "package_placemark_count": placements, "limits": {"max_placemarks": MAX_PLACEMARKS, "max_vertices": MAX_VERTICES, "max_payload_bytes": MAX_PAYLOAD_BYTES, "max_diagnostic_markers": MAX_DIAGNOSTIC_MARKERS}}


def _write_readme(path: Path, package_id: str, kind: str, report: dict[str, object], metadata: dict[str, object], output_directory: str) -> None:
    status = str(report["status"])
    payloads = {}
    for name in ("source-network-inspection.kmz", "source-evidence.jsonl", "review-cases.csv", "review-observations-template.csv"):
        payload = path.parent / name
        payloads[name] = {"bytes": payload.stat().st_size, "sha256": _hash(payload)}
    source = metadata["source"]
    inventory_evidence = source.get("inventory_evidence", {})
    attribution = inventory_evidence.get("license_reference") or "License reference not present in the source inventory"
    license_status = inventory_evidence.get("license_status") or "License status unknown; this local prototype is not distribution clearance"
    path.write_text(
        f"# Google Earth source-network inspection\n\nDataset kind: **{kind}**. Status: **{status}**. Package ID: `{package_id}`.\n\n"
        f"Local package folder: `{output_directory}`.\n\n"
        "Open `source-network-inspection.kmz` with Google Earth Local KML. This package shows source evidence only; it does not classify pedestrian eligibility, establish route completeness, or infer connections from visual line crossings. Geometry is ground-clamped; vertical separation is not represented. "
        + ("This selection contains no network ways; do not treat it as a network." if status == "empty" else "")
        + "\n\n"
        "Folders: Package information, Review cases, Coverage, Source nodes, Source segments, Source ways, Diagnostics. Full node/way/relation evidence is in `source-evidence.jsonl`. `review-cases.csv` lists the navigation cases; enter observations in `review-observations-template.csv`. Keep the package unchanged. Google Earth compatibility remains untested until the manual viewer trial is recorded.\n\n"
        f"Counts: `{json.dumps(report['counts'], sort_keys=True)}`.\n\n"
        f"Source attribution/licensing recorded by inventory: `{attribution}`; status: `{license_status}`. This packet is not approved for redistribution.\n\n"
        "File checksums (SHA-256):\n\n"
        + "\n".join(f"- `{name}` — {record['bytes']} bytes — `{record['sha256']}`" for name, record in payloads.items())
        + "\n\nDo not upload the package to a cloud project during this local inspection workflow. Map imagery still uses the network.\n",
        encoding="utf-8",
        newline="\n",
    )


def _validate_candidate(candidate: Path, package_id: str) -> dict[str, object]:
    manifest_path = candidate / "inspection-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("inspection_version") != INSPECTION_VERSION or manifest.get("package_id") != package_id:
        raise InspectionFailure("Inspection manifest version or package ID is invalid")
    files = manifest.get("files")
    required = {"source-network-inspection.kmz", "source-evidence.jsonl", "review-cases.csv", "review-observations-template.csv", "README.md"}
    if not isinstance(files, dict) or set(files) != required:
        raise InspectionFailure("Inspection manifest file inventory is incomplete")
    size = 0
    for name, record in files.items():
        path = candidate / name
        if not path.is_file() or path.stat().st_size != record.get("bytes") or _hash(path) != record.get("sha256"):
            raise InspectionFailure(f"Inspection payload does not match its manifest: {name}")
        size += path.stat().st_size
    if size > MAX_PAYLOAD_BYTES:
        raise InspectionFailure(f"Inspection payload exceeds {MAX_PAYLOAD_BYTES} byte first-trial limit")
    kmz = candidate / "source-network-inspection.kmz"
    expected_members = {"doc.kml", "icons/source-node.png", "icons/review-case.png", "icons/diagnostic.png"}
    with zipfile.ZipFile(kmz) as archive:
        if set(archive.namelist()) != expected_members or archive.testzip() is not None:
            raise InspectionFailure("KMZ members or CRC check are invalid")
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(archive.read("doc.kml"))
        except ET.ParseError as error:
            raise InspectionFailure(f"KML XML is invalid: {error}") from error
        ns = {"k": "http://www.opengis.net/kml/2.2"}
        if root.tag != "{http://www.opengis.net/kml/2.2}kml" or root.find("k:Document", ns) is None:
            raise InspectionFailure("KML namespace or Document element is invalid")
        if root.findall(".//k:NetworkLink", ns):
            raise InspectionFailure("Network links are not permitted in a local inspection package")
        hrefs = [element.text or "" for element in root.findall(".//k:href", ns)]
        if any("://" in href or href.startswith(("/", "\\")) or ".." in Path(href).parts for href in hrefs):
            raise InspectionFailure("KML contains a nonlocal or unsafe resource reference")
        for name in expected_members - {"doc.kml"}:
            if not archive.read(name).startswith(b"\x89PNG\r\n\x1a\n"):
                raise InspectionFailure(f"KML icon is missing or is not PNG: {name}")
        placemarks = root.findall(".//k:Placemark", ns)
        ids = [p.get("id") for p in placemarks]
        if len(ids) != len(set(ids)) or any(not item or not item[0].isalpha() for item in ids):
            raise InspectionFailure("KML Placemark IDs are missing, invalid, or duplicated")
        if len(placemarks) != manifest["counts"]["package_placemark_count"]:
            raise InspectionFailure("KML placemark count does not match the manifest")
        folders = {folder.findtext("k:name", namespaces=ns): folder for folder in root.findall(".//k:Folder", ns)}
        expected_folders = {"Package information", "Review cases", "Coverage", "Source nodes", "Source segments", "Source ways", "Diagnostics"}
        if not expected_folders.issubset(folders):
            raise InspectionFailure("KML is missing one or more required review folders")
        for folder_name, expected_count in (("Package information", 1), ("Review cases", manifest["counts"]["review_cases"]), ("Coverage", manifest["counts"]["coverage"]), ("Source nodes", manifest["counts"]["source_nodes"]), ("Source segments", manifest["counts"]["source_segments"]), ("Source ways", manifest["counts"]["source_ways"]), ("Diagnostics", manifest["counts"]["diagnostic_markers"])):
            actual = len(folders[folder_name].findall("k:Placemark", ns))
            if actual != expected_count:
                raise InspectionFailure(f"KML folder count mismatch for {folder_name}: {actual} != {expected_count}")
        for node in root.findall(".//k:coordinates", ns):
            for coordinate in (node.text or "").split():
                parts = coordinate.split(",")
                if len(parts) < 2 or not all(math.isfinite(float(v)) for v in parts[:2]):
                    raise InspectionFailure("KML contains malformed or nonfinite coordinates")
                lon, lat = map(float, parts[:2])
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise InspectionFailure("KML coordinate is outside valid longitude/latitude range")
        _validate_source_features(candidate, folders, ns, manifest["counts"])
    return manifest


def _validate_source_features(candidate: Path, folders: dict[str | None, object], ns: dict[str, str], counts: dict[str, object]) -> None:
    evidence: dict[str, dict[str, dict[str, object]]] = {"node": {}, "way": {}, "relation": {}, "segment": {}}
    with (candidate / "source-evidence.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            kind = record.get("entity_type")
            source_id = str(record.get("osm_id") if kind != "segment" else record.get("segment_id"))
            if kind not in evidence or source_id in evidence[kind]:
                raise InspectionFailure("Source evidence has an unknown entity kind or duplicate source identity")
            evidence[kind][source_id] = record
    expected_evidence = {"node": counts["source_nodes"], "way": counts["source_ways"], "relation": counts["source_relations"], "segment": counts["source_segments"]}
    if any(len(evidence[kind]) != count for kind, count in expected_evidence.items()):
        raise InspectionFailure("Source evidence entity counts do not reconcile with the package manifest")

    def data(placemark: object) -> dict[str, str]:
        return {item.get("name", ""): item.findtext("k:value", namespaces=ns) or "" for item in placemark.findall("k:ExtendedData/k:Data", ns)}

    def geometry(placemark: object) -> list[tuple[float, float]]:
        nodes = placemark.findall(".//k:coordinates", ns)
        if len(nodes) != 1:
            raise InspectionFailure("A source placemark must have one coordinate sequence")
        parts = (nodes[0].text or "").split()
        return [(float(row.split(",")[0]), float(row.split(",")[1])) for row in parts]

    def same_coordinates(actual: list[tuple[float, float]], expected: list[tuple[float, float]]) -> bool:
        return len(actual) == len(expected) and all(math.isclose(ax, ex, rel_tol=0, abs_tol=1e-9) and math.isclose(ay, ey, rel_tol=0, abs_tol=1e-9) for (ax, ay), (ex, ey) in zip(actual, expected))

    node_coords: dict[str, tuple[float, float]] = {}
    for placemark in folders["Source nodes"].findall("k:Placemark", ns):
        fields = data(placemark)
        source_id = fields.get("osm_id", "")
        record = evidence["node"].get(source_id)
        if record is None or json.loads(fields.get("tags_json", "null")) != record["tags"]:
            raise InspectionFailure(f"KML node ID or raw tags do not match source evidence: {source_id}")
        expected = (float(record["lon"]), float(record["lat"]))
        if not same_coordinates(geometry(placemark), [expected]):
            raise InspectionFailure(f"KML node coordinate does not match source evidence: {source_id}")
        node_coords[source_id] = expected

    seen_ways: set[str] = set()
    for placemark in folders["Source ways"].findall("k:Placemark", ns):
        fields = data(placemark)
        source_id = fields.get("osm_id", "")
        record = evidence["way"].get(source_id)
        if record is None or json.loads(fields.get("tags_json", "null")) != record["tags"] or json.loads(fields.get("node_refs_json", "null")) != record["node_refs"]:
            raise InspectionFailure(f"KML way identity, ordered refs, or tags do not match source evidence: {source_id}")
        try:
            expected = [node_coords[str(node_id)] for node_id in record["node_refs"]]
        except KeyError as error:
            raise InspectionFailure(f"KML way references a node absent from source evidence: {error}") from error
        if not same_coordinates(geometry(placemark), expected):
            raise InspectionFailure(f"KML way coordinate order does not match its source references: {source_id}")
        seen_ways.add(source_id)

    seen_segments: set[str] = set()
    for placemark in folders["Source segments"].findall("k:Placemark", ns):
        fields = data(placemark)
        source_id = fields.get("segment_id", "")
        record = evidence["segment"].get(source_id)
        if record is None or fields.get("way_id") != record.get("way_id") or fields.get("from_node_id") != record.get("from_node_id") or fields.get("to_node_id") != record.get("to_node_id") or fields.get("sequence") != str(record.get("sequence")) or json.loads(fields.get("tags_json", "null")) != json.loads(record["tags_json"]):
            raise InspectionFailure(f"KML segment identity, pair, sequence, or tags do not match source evidence: {source_id}")
        expected = [(float(pair[0]), float(pair[1])) for pair in record["coordinates_lon_lat"]]
        if not same_coordinates(geometry(placemark), expected):
            raise InspectionFailure(f"KML segment coordinates do not match source evidence: {source_id}")
        for field in ("length_geodesic_m", "length_projected_m"):
            if not math.isclose(float(fields[field]), float(record[field]), rel_tol=1e-12, abs_tol=1e-8):
                raise InspectionFailure(f"KML segment length does not match source evidence: {source_id}/{field}")
        seen_segments.add(source_id)
    if len(node_coords) != len(evidence["node"]) or len(seen_ways) != len(evidence["way"]) or len(seen_segments) != len(evidence["segment"]):
        raise InspectionFailure("KML source-feature identities are incomplete or duplicated")


def _build_candidate(config_path: Path, extraction_path: Path, export_path: Path, candidate: Path, package_id: str, dataset_kind: str, review_profile: str) -> dict[str, object]:
    config = load_config(config_path)
    extraction_dir, metadata, identity = _validate_extraction(config, extraction_path)
    metadata["station_lonlat"] = list(config.station_lonlat)
    metadata["review_profile"] = review_profile
    gpkg_dir = Path(export_path).resolve()
    try:
        gpkg_dir.relative_to(config.output_root.resolve())
    except ValueError as error:
        raise ConfigError("GeoPackage export directory must be inside the configured generated output root") from error
    report_path = gpkg_dir / "run-report.json"
    gpkg_path = gpkg_dir / "source-network.gpkg"
    export_report = json.loads(report_path.read_text(encoding="utf-8"))
    if export_report.get("report_version") != "source-network-export-1" or export_report.get("status") not in {"pass", "pass_with_warnings", "empty"}:
        raise InspectionFailure("A completed source-network GeoPackage export report is required")
    if export_report.get("extraction_run_id") != metadata.get("run_id") or export_report.get("code_identity", {}).get("sha256") != identity["sha256"]:
        raise InspectionFailure("GeoPackage export report has mismatched extraction or code identity")
    if export_report.get("output", {}).get("sha256") != _hash(gpkg_path) or export_report.get("output", {}).get("bytes") != gpkg_path.stat().st_size:
        raise InspectionFailure("GeoPackage bytes do not match its completed export report")
    if export_report.get("extraction_metadata_sha256") != _hash(extraction_dir / "extraction.json"):
        raise InspectionFailure("GeoPackage report does not link to the current extraction metadata")
    if export_report.get("configuration", {}).get("sha256") != _hash(config.config_path):
        raise InspectionFailure("GeoPackage report configuration hash is stale")
    if dataset_kind not in {"synthetic", "regional"} or review_profile not in {"topology", "diagnostic", "regional"}:
        raise ConfigError("dataset kind or review profile is invalid")
    if (dataset_kind == "regional") != (review_profile == "regional"):
        raise ConfigError("regional datasets require the regional review profile; synthetic datasets require topology or diagnostic")
    candidate.mkdir(parents=True, exist_ok=False)
    measurements = _write_document(candidate, metadata, {**export_report, "output": {**export_report["output"], "absolute_path": gpkg_path}, "extraction_absolute_path": extraction_dir}, dataset_kind, package_id)
    package_status = "empty" if metadata["status"] == "empty" else "complete"
    output_directory = (config.output_root / package_id).relative_to(config.repo_root).as_posix()
    _write_readme(candidate / "README.md", package_id, dataset_kind, {"status": package_status, "counts": measurements["counts"]}, metadata, output_directory)
    payload_names = ["source-network-inspection.kmz", "source-evidence.jsonl", "review-cases.csv", "review-observations-template.csv", "README.md"]
    manifest = {
        "inspection_version": INSPECTION_VERSION,
        "status": "empty" if metadata["status"] == "empty" else "complete",
        "package_id": package_id,
        "dataset_kind": dataset_kind,
        "review_profile": review_profile,
        "region_id": metadata["region_id"],
        "contract_version": metadata["contract_version"],
        "selection_id": metadata["selection_id"],
        "created_at_utc": datetime.now(UTC).isoformat(),
        "code_identity": {"algorithm": identity["algorithm"], "sha256": identity["sha256"], "manifest": identity["manifest"]},
        "configuration": {"path": config.config_path.relative_to(config.repo_root).as_posix(), "sha256": _hash(config.config_path)},
        "source": metadata["source"],
        "source_inventory": {"path": metadata["accepted_source_inventory"]["path"], "sha256": _hash(config.repo_root / metadata["accepted_source_inventory"]["path"]), "run_report_path": metadata["accepted_source_inventory"]["run_report_path"], "run_report_sha256": _hash(config.repo_root / metadata["accepted_source_inventory"]["run_report_path"])},
        "coverage": metadata["coverage"],
        "station_lonlat": metadata["station_lonlat"],
        "storage_crs": "EPSG:4326",
        "inspection_crs": config.inspection_crs,
        "length_method": config.length_method,
        "environment": runtime_versions(),
        "extraction": {"run_id": metadata["run_id"], "metadata_sha256": _hash(extraction_dir / "extraction.json"), "directory": extraction_dir.relative_to(config.repo_root).as_posix()},
        "geopackage": {"export_run_id": export_report["export_run_id"], "sha256": export_report["output"]["sha256"], "report_sha256": _hash(report_path), "path": gpkg_path.relative_to(config.repo_root).as_posix()},
        "counts": measurements["counts"],
        "source_gpkg_counts": measurements["source_gpkg_counts"],
        "source_evidence_semantic_sha256": measurements["evidence_semantic_sha256"],
        "feature_vertex_count": measurements["feature_vertex_count"],
        "package_placemark_count": measurements["package_placemark_count"],
        "limits": measurements["limits"],
        "partition": {"id": "whole-input-1", "scope": metadata["coverage"]["extract_bbox"], "partial": False},
        "known_limitations": ["Source evidence only; no pedestrian eligibility or routing.", "Ground-clamped KML does not encode measured vertical separation.", "Visual overlap does not establish a source-node connection.", "Expanded comparison bounds are planned metadata unless a separate extraction exists.", "Feature, vertex, byte, and diagnostic-marker limits are conservative first-trial caps, not Google Earth capacity claims.", "Regional case IDs and review outcomes require pinned-source human review.", "Google Earth UI compatibility and user acceptance are not assessed by this export."],
        "manual_viewer_checks": {"google_earth_import": "not_run", "folder_toggles": "not_run", "feature_selection": "not_run", "description_legibility": "not_run", "human_usability_acceptance": "not_run"},
        "checks": {"export_report_and_gpkg_hash_match": True, "extraction_identity_match": True, "feature_and_vertex_limits": True, "evidence_counts_reconciled": True, "source_ids_tags_refs_and_coordinates_reconciled": True, "kml_xml_namespace_and_unique_ids_valid": True, "coordinate_ranges_valid": True, "folder_counts_reconciled": True, "kmz_members_and_crc_valid": True, "kmz_resources_are_local": True},
        "files": {},
    }
    (candidate / "inspection-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    for name in payload_names:
        path = candidate / name
        if path.stat().st_size > MAX_PAYLOAD_BYTES:
            raise InspectionFailure(f"Payload file exceeds trial byte limit: {name}")
        manifest["files"][name] = {"bytes": path.stat().st_size, "sha256": _hash(path)}
    (candidate / "inspection-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    _validate_candidate(candidate, package_id)
    return {"status": manifest["status"], "manifest": manifest}


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _promote_directory(source: Path, destination: Path) -> None:
    for delay in (0.1, 0.25, 0.5, None):
        try:
            os.replace(source, destination)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in {5, 32} or delay is None:
                raise
            time.sleep(delay)


def _input_hashes(config: PipelineConfig, extraction: Path, metadata: dict[str, object], gpkg_path: Path, report_path: Path) -> dict[str, str]:
    inventory = metadata["accepted_source_inventory"]
    inventory_path = (config.repo_root / inventory["path"]).resolve()
    inventory_report_path = (config.repo_root / inventory["run_report_path"]).resolve()
    for path in (inventory_path, inventory_report_path):
        try:
            path.relative_to(config.repo_root.resolve())
        except ValueError as error:
            raise InspectionFailure("Accepted source inventory paths must remain inside the repository") from error
    return {
        "configuration": _hash(config.config_path),
        "source_osm": _hash(config.sources["osm"].path),
        "source_inventory": _hash(inventory_path),
        "source_inventory_report": _hash(inventory_report_path),
        "extraction_metadata": _hash(extraction / "extraction.json"),
        "extraction_report": _hash(extraction / "run-report.json"),
        "extraction_code_manifest": _hash(extraction / "code-manifest.json"),
        "nodes": _hash(extraction / "nodes.jsonl"),
        "ways": _hash(extraction / "ways.jsonl"),
        "relations": _hash(extraction / "relations.jsonl"),
        "gpkg": _hash(gpkg_path),
        "gpkg_report": _hash(report_path),
    }


def build_worker(config_path: Path, extraction_path: Path, export_path: Path, candidate: Path, result_path: Path, package_id: str, dataset_kind: str, review_profile: str) -> int:
    try:
        value = _build_candidate(config_path, extraction_path, export_path, candidate, package_id, dataset_kind, review_profile)
        _atomic_json(result_path, value)
        return 0
    except Exception as error:
        _atomic_json(result_path, {"status": "fail", "error": str(error)})
        print(f"Google Earth package generation failed: {type(error).__name__}: {error}")
        return 1


def export_inspection_package(config_path: Path, extraction_path: Path, export_path: Path, dataset_kind: str, review_profile: str) -> tuple[int, dict[str, object]]:
    """Supervise, validate, and promote a source-network KML/KMZ review package."""
    stage_dir: Path | None = None
    package_id: str | None = None
    try:
        config = load_config(config_path)
        errors = environment_errors()
        if errors:
            return 1, {"status": "fail", "phase": "environment", "errors": errors}
        extraction, metadata, identity = _validate_extraction(config, extraction_path)
        export_dir = Path(export_path).resolve()
        report_path = export_dir / "run-report.json"
        if not report_path.is_file():
            raise InspectionFailure("GeoPackage export completion report is missing")
        gpkg_path = export_dir / "source-network.gpkg"
        input_hashes = _input_hashes(config, extraction, metadata, gpkg_path, report_path)
        package_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        final_dir = config.output_root / package_id
        stage_dir = config.repo_root / "data" / "staging" / "prototype" / package_id
        if final_dir.exists() or stage_dir.exists():
            raise FileExistsError(f"Refusing to reuse inspection package directory: {package_id}")
        stage_dir.mkdir(parents=True)
        candidate = stage_dir / "candidate"
        result_path = stage_dir / "worker-result.json"
        log_path = stage_dir / "earth-worker.log"
        if dataset_kind not in {"synthetic", "regional"} or review_profile not in {"topology", "diagnostic", "regional"} or ((dataset_kind == "regional") != (review_profile == "regional")):
            raise ConfigError("dataset kind and review profile are incompatible")
        command = [os.fspath(Path(os.sys.executable)), "-m", "flm_pipeline", "_earth-worker", "--config", str(config.config_path), "--extraction", str(extraction), "--gpkg-export", str(export_dir), "--candidate", str(candidate), "--result", str(result_path), "--package-id", package_id, "--dataset-kind", dataset_kind, "--review-profile", review_profile]
        from .cli import _supervise
        supervised = _supervise(command, config.repo_root, log_path, config.limit_seconds, config.limit_rss_bytes)
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {"status": "fail", "error": "Worker result missing"}
        if supervised["exit_code"] != 0 or supervised["failure_reason"] is not None or result.get("status") not in {"complete", "empty"}:
            raise InspectionFailure(f"Supervised worker failed: {result.get('error') or supervised['failure_reason'] or supervised['exit_code']}")
        identity_after = code_identity()
        final_hashes = _input_hashes(config, extraction, metadata, gpkg_path, report_path)
        if identity_after["sha256"] != identity["sha256"] or input_hashes != final_hashes:
            raise InspectionFailure("Code or source/export inputs changed while package was being generated")
        manifest = _validate_candidate(candidate, package_id)
        manifest["resource_supervision"] = {"duration_seconds": supervised["duration_seconds"], "sampled_peak_rss_bytes": supervised["sampled_peak_rss_bytes"], "sample_interval_seconds": supervised["sample_interval_seconds"], "configured_timeout_seconds": config.limit_seconds, "configured_rss_limit_bytes": config.limit_rss_bytes}
        _atomic_json(candidate / "inspection-manifest.json", manifest)
        manifest = _validate_candidate(candidate, package_id)
        report = {"report_version": INSPECTION_VERSION, "status": "pass" if result["status"] == "complete" else "empty", "package_id": package_id, "dataset_kind": dataset_kind, "review_profile": review_profile, "created_at_utc": datetime.now(UTC).isoformat(), "code_identity_sha256": identity["sha256"], "input_hashes": input_hashes, "worker": supervised, "counts": manifest["counts"], "manual_viewer_checks": manifest["manual_viewer_checks"], "output_directory": final_dir.relative_to(config.repo_root).as_posix(), "files": manifest["files"], "limitations": manifest["known_limitations"]}
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        _promote_directory(candidate, final_dir)
        report_path_final = final_dir / "run-report.json"
        report["files"] = {**report["files"], "inspection-manifest.json": {"bytes": (final_dir / "inspection-manifest.json").stat().st_size, "sha256": _hash(final_dir / "inspection-manifest.json")}}
        try:
            _atomic_json(report_path_final, report)
        except OSError as error:
            try:
                final_dir.resolve().relative_to(config.output_root.resolve())
                for child in final_dir.iterdir():
                    if not child.is_file():
                        raise OSError(f"unexpected directory in incomplete inspection package: {child.name}")
                    child.unlink()
                final_dir.rmdir()
            except OSError as cleanup_error:
                raise InspectionFailure(f"Final report write failed and incomplete output cleanup failed: {cleanup_error}") from error
            raise InspectionFailure("Final report write failed; the incomplete output directory was removed") from error
        return 0, {"status": report["status"], "package_id": package_id, "dataset_kind": dataset_kind, "review_profile": review_profile, "output_directory": final_dir.relative_to(config.repo_root).as_posix(), "kmz": (final_dir / "source-network-inspection.kmz").relative_to(config.repo_root).as_posix(), "manifest": (final_dir / "inspection-manifest.json").relative_to(config.repo_root).as_posix(), "run_report": report_path_final.relative_to(config.repo_root).as_posix(), "counts": report["counts"], "files": report["files"], "worker": supervised}
    except (ConfigError, ExportFailure, InspectionFailure, OSError, ValueError, TypeError, KeyError) as error:
        stage_relative = stage_dir.relative_to(config.repo_root).as_posix() if stage_dir is not None and stage_dir.exists() else None
        if stage_dir is not None and stage_dir.exists():
            try:
                _atomic_json(stage_dir / "run-report.json", {"report_version": INSPECTION_VERSION, "status": "fail", "package_id": package_id, "dataset_kind": dataset_kind, "review_profile": review_profile, "finished_at_utc": datetime.now(UTC).isoformat(), "errors": [str(error)], "worker_result": (json.loads((stage_dir / "worker-result.json").read_text(encoding="utf-8")) if (stage_dir / "worker-result.json").is_file() else None), "worker_log": (stage_dir / "earth-worker.log").name})
            except (OSError, ValueError):
                pass
        return 1, {"status": "fail", "phase": "preflight_or_worker", "errors": [str(error)], "stage_directory": stage_relative}

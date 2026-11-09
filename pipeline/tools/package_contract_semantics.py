"""Contract-design reference for deterministic semantic identity, not package validation."""
import hashlib
import json
import math
import struct


def tagged(value):
    """Unambiguous tagged JSON; numbers are IEEE754 big-endian binary64 hex."""
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("Nonfinite semantic value")
        return ["number", struct.pack(">d", 0.0 if value == 0 else value).hex()]
    if isinstance(value, str):
        if not value.isascii():
            raise ValueError("Semantic projection v1 requires ASCII strings")
        return ["string", value]
    if isinstance(value, list):
        return ["array", [tagged(item) for item in value]]
    if isinstance(value, dict):
        return ["object", [[key, tagged(value[key])] for key in sorted(value)]]
    raise ValueError("Unsupported semantic value")


def graph_digest(identity, coverage, diagnostics, nodes, segments, arcs):
    projection = {"semantic_version": "flm-graph-semantic-1", "identity": identity, "coverage": coverage, "diagnostics": diagnostics, "nodes": sorted(nodes, key=lambda r: r["node_id"]), "segments": sorted(segments, key=lambda r: r["candidate_id"]), "arcs": sorted(arcs, key=lambda r: r["edge_id"])}
    canonical = json.dumps(tagged(projection), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()

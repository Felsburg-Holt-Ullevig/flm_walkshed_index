"""Strict loading for the accepted experimental pedestrian-policy settings."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import tomllib
from typing import Any


class PedestrianConfigError(ValueError):
    """Raised when pedestrian settings do not match the accepted contract."""


@dataclass(frozen=True)
class PedestrianSettings:
    rule_version: str
    scenario_id: str
    status: str
    rule_authority: str
    comparison_scenario_id: str
    reference_revision: str
    length_unit: str
    time_unit: str
    speed_mph: float
    feet_per_mile: int
    meters_per_international_foot: float
    crossing_delay_model: str
    steps_cost_model: str
    slope_cost_model: str
    origin_mode: str
    access_connectors: str
    snap_distance_ft: str
    unknown_candidates: str
    unknown_node: str
    blocked_node: str
    config_path: Path
    config_sha256: str


_EXPECTED = {
    "rule_version": "pedestrian-policy-0.3",
    "scenario_id": "public-walk-experiment-0.3",
    "status": "accepted_experimental",
    "rule_authority": "pipeline/pedestrian-policy.md",
    "comparison_scenario_id": "reference-classification-6068f1b",
    "reference_revision": "6068f1b8719d025426443230bb4a39a296b4f583",
    "length_unit": "international_foot",
    "time_unit": "second",
    "feet_per_mile": 5280,
    "crossing_delay_model": "not_modeled",
    "steps_cost_model": "same_base_speed_with_warning",
    "slope_cost_model": "not_modeled",
    "origin_mode": "verified_source_node",
    "access_connectors": "disabled",
    "snap_distance_ft": "not_defined",
    "unknown_candidates": "block_analytical_promotion",
    "unknown_node": "quarantine_incident_segments",
    "blocked_node": "exclude_incident_segments",
}
_SPEED_MPH = 4500 / 1609.344
_METERS_PER_FOOT = 0.3048


def _expect_table(raw: Any, key: str, expected: set[str]) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise PedestrianConfigError(f"{key} must be a table")
    extra = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if extra or missing:
        details = []
        if extra:
            details.append(f"unknown fields: {', '.join(extra)}")
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        raise PedestrianConfigError(f"{key}: {'; '.join(details)}")
    return value


def load_pedestrian_settings(path: str | Path) -> PedestrianSettings:
    """Load and validate the accepted settings; unsupported policy versions fail closed."""
    config_path = Path(path).resolve()
    try:
        payload = config_path.read_bytes()
        raw = tomllib.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PedestrianConfigError(f"Could not read pedestrian TOML configuration: {error}") from error
    if not isinstance(raw, dict):
        raise PedestrianConfigError("Pedestrian configuration root must be a TOML table")
    expected_top = {
        "rule_version", "scenario_id", "status", "rule_authority", "comparison_scenario_id",
        "reference_revision", "cost", "origin", "completeness",
    }
    extra = sorted(set(raw) - expected_top)
    missing = sorted(expected_top - set(raw))
    if extra or missing:
        details = []
        if extra:
            details.append(f"unknown fields: {', '.join(extra)}")
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        raise PedestrianConfigError(f"configuration: {'; '.join(details)}")
    for key, expected in _EXPECTED.items():
        if key in {"feet_per_mile", "length_unit", "time_unit", "crossing_delay_model", "steps_cost_model", "slope_cost_model"}:
            continue
        if key in {"origin_mode", "access_connectors", "snap_distance_ft", "unknown_candidates", "unknown_node", "blocked_node"}:
            continue
        if raw.get(key) != expected:
            raise PedestrianConfigError(f"{key} must be {expected!r}")

    cost = _expect_table(raw, "cost", {
        "length_unit", "time_unit", "speed_mph", "feet_per_mile", "meters_per_international_foot",
        "crossing_delay_model", "steps_cost_model", "slope_cost_model",
    })
    origin = _expect_table(raw, "origin", {"mode", "access_connectors", "snap_distance_ft"})
    completeness = _expect_table(raw, "completeness", {"unknown_candidates", "unknown_node", "blocked_node"})
    for key, expected in {
        "length_unit": "international_foot",
        "time_unit": "second",
        "feet_per_mile": 5280,
        "crossing_delay_model": "not_modeled",
        "steps_cost_model": "same_base_speed_with_warning",
        "slope_cost_model": "not_modeled",
    }.items():
        actual = cost.get(key)
        if actual != expected:
            raise PedestrianConfigError(f"cost.{key} must be {expected!r}")
    for key, expected in {
        "mode": "verified_source_node",
        "access_connectors": "disabled",
        "snap_distance_ft": "not_defined",
    }.items():
        actual = origin.get(key)
        if actual != expected:
            raise PedestrianConfigError(f"origin.{key} must be {expected!r}")
    for key, expected in {
        "unknown_candidates": "block_analytical_promotion",
        "unknown_node": "quarantine_incident_segments",
        "blocked_node": "exclude_incident_segments",
    }.items():
        actual = completeness.get(key)
        if actual != expected:
            raise PedestrianConfigError(f"completeness.{key} must be {expected!r}")
    speed = cost["speed_mph"]
    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(float(speed)) or not math.isclose(float(speed), _SPEED_MPH, rel_tol=0, abs_tol=1e-15):
        raise PedestrianConfigError("cost.speed_mph must preserve the exact accepted 1.25 m/s conversion")
    meters_per_foot = cost["meters_per_international_foot"]
    if isinstance(meters_per_foot, bool) or not isinstance(meters_per_foot, (int, float)) or float(meters_per_foot) != _METERS_PER_FOOT:
        raise PedestrianConfigError("cost.meters_per_international_foot must equal 0.3048")
    if isinstance(cost["feet_per_mile"], bool) or not isinstance(cost["feet_per_mile"], int):
        raise PedestrianConfigError("cost.feet_per_mile must be an integer")
    if not isinstance(raw["rule_authority"], str) or not raw["rule_authority"]:
        raise PedestrianConfigError("rule_authority must be a non-empty string")
    return PedestrianSettings(
        rule_version=raw["rule_version"], scenario_id=raw["scenario_id"], status=raw["status"],
        rule_authority=raw["rule_authority"], comparison_scenario_id=raw["comparison_scenario_id"],
        reference_revision=raw["reference_revision"], length_unit=cost["length_unit"],
        time_unit=cost["time_unit"], speed_mph=float(speed), feet_per_mile=cost["feet_per_mile"],
        meters_per_international_foot=float(meters_per_foot), crossing_delay_model=cost["crossing_delay_model"],
        steps_cost_model=cost["steps_cost_model"], slope_cost_model=cost["slope_cost_model"],
        origin_mode=origin["mode"], access_connectors=origin["access_connectors"],
        snap_distance_ft=origin["snap_distance_ft"], unknown_candidates=completeness["unknown_candidates"],
        unknown_node=completeness["unknown_node"], blocked_node=completeness["blocked_node"],
        config_path=config_path, config_sha256=hashlib.sha256(payload).hexdigest(),
    )

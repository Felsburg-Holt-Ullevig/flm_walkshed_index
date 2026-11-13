"""Scenario-specific pedestrian speed contracts preserve accepted history."""
from pathlib import Path

import pytest

from flm_pipeline.pedestrian_config import PedestrianConfigError, load_pedestrian_settings


ROOT = Path(__file__).resolve().parents[2]
ACCEPTED = ROOT / "pipeline/config/pedestrian-policy.example.toml"


def _write_variant(tmp_path, scenario_id, speed):
    text = ACCEPTED.read_text(encoding="utf-8")
    text = text.replace('scenario_id = "public-walk-experiment-0.3"', f'scenario_id = "{scenario_id}"')
    text = text.replace("speed_mph = 2.796170365068003", f"speed_mph = {speed}")
    path = tmp_path / "policy.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_original_policy_retains_accepted_conversion():
    settings = load_pedestrian_settings(ACCEPTED)
    assert settings.scenario_id == "public-walk-experiment-0.3"
    assert settings.speed_mph == 4500 / 1609.344


def test_original_policy_retains_historical_float_tolerance(tmp_path):
    settings = load_pedestrian_settings(_write_variant(tmp_path, "public-walk-experiment-0.3", "2.7961703650680035"))
    assert settings.scenario_id == "public-walk-experiment-0.3"


def test_new_reference_scenario_accepts_exact_2_8_mph(tmp_path):
    settings = load_pedestrian_settings(_write_variant(tmp_path, "plan-a-walk-reference-2.8-v1", "2.8"))
    assert settings.scenario_id == "plan-a-walk-reference-2.8-v1"
    assert settings.speed_mph == 2.8


@pytest.mark.parametrize(
    ("scenario_id", "speed"),
    [
        ("public-walk-experiment-0.3", "2.8"),
        ("plan-a-walk-reference-2.8-v1", "2.796170365068003"),
        ("unapproved-scenario", "2.8"),
    ],
)
def test_scenario_and_speed_must_be_an_approved_pair(tmp_path, scenario_id, speed):
    with pytest.raises(PedestrianConfigError):
        load_pedestrian_settings(_write_variant(tmp_path, scenario_id, speed))

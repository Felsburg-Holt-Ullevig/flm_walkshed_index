"""Timeout and sparse-report handling for step 3 sample preparation."""
from pathlib import Path
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "pipeline" / "tools"))
import prepare_walk_samples as prepare  # noqa: E402


def test_case_config_preserves_1200_second_default_and_supports_7200():
    source = ROOT / "pipeline" / "config" / "denver-source.example.toml"
    bbox = (-104.72, 40.40, -104.67, 40.45)
    origin = (-104.69, 40.42)

    default = tomllib.loads(prepare._config_text(source, bbox, origin, Path("data/generated/example"), "G01"))
    extended = tomllib.loads(prepare._config_text(source, bbox, origin, Path("data/generated/example"), "G01", 7200))

    assert default["limits"]["seconds"] == 1200
    assert extended["limits"]["seconds"] == 7200
    assert extended["sources"] == default["sources"]
    assert extended["extract_bbox"] == list(bbox)
    assert extended["station_lonlat"] == list(origin)


@pytest.mark.parametrize("value", ["1", "7200", "1200"])
def test_stage_seconds_parser_accepts_positive_integers(value):
    assert prepare._positive_stage_seconds(value) == int(value)


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "invalid"])
def test_stage_seconds_parser_rejects_nonpositive_or_noninteger_values(value):
    with pytest.raises(prepare.argparse.ArgumentTypeError):
        prepare._positive_stage_seconds(value)


def test_stage_seconds_replacement_requires_one_setting():
    with pytest.raises(ValueError, match="exactly one"):
        prepare._replace_stage_seconds("seconds = 1200\nseconds = 900\n", 7200)
    with pytest.raises(ValueError, match="positive integer"):
        prepare._replace_stage_seconds("seconds = 1200\n", 0)


def test_missing_relation_counts_default_to_zero_and_sparse_counts_are_preserved():
    assert prepare._relation_counts({}) == {"retained": 0, "unsupported": 0, "unresolved_members": 0}
    assert prepare._relation_counts({"relations": {"retained": 2}}) == {
        "retained": 2, "unsupported": 0, "unresolved_members": 0,
    }


@pytest.mark.parametrize("relations", [None, {"retained": True}, {"unsupported": -1}])
def test_invalid_relation_counts_are_rejected(relations):
    with pytest.raises(ValueError):
        prepare._relation_counts({"relations": relations})

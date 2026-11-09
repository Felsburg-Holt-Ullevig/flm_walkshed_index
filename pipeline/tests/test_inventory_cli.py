from dataclasses import replace
import json
from pathlib import Path

from flm_pipeline import cli
from flm_pipeline.config import load_config


def test_inventory_rejects_failed_worker_even_with_passing_result(tmp_path, monkeypatch):
    original = load_config(Path(__file__).resolve().parents[1] / "config/denver-source.example.toml")
    config_path = tmp_path / "config.toml"
    config_path.write_text("fixture", encoding="utf-8")
    config = replace(original, repo_root=tmp_path, config_path=config_path, output_root=tmp_path / "generated")
    monkeypatch.setattr(cli, "load_config", lambda _: config)
    monkeypatch.setattr(cli, "environment_errors", lambda: [])

    def failed_worker(command, *_args):
        result = Path(command[command.index("--result") + 1])
        result.write_text(json.dumps({"inventory": {"inventory_status": "pass", "sources": {}}}), encoding="utf-8")
        return {"exit_code": 7, "duration_seconds": 0, "sampled_peak_rss_bytes": 0, "failure_reason": None, "log": "fixture.log"}

    monkeypatch.setattr(cli, "_supervise", failed_worker)
    code, result = cli.inventory(config_path)
    assert code == 1
    assert result["status"] == "fail"
    report = json.loads((tmp_path / result["run_report"]).read_text(encoding="utf-8"))
    assert "worker exited with 7" in report["diagnostics"]

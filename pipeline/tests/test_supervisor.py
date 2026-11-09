from __future__ import annotations

from pathlib import Path
import sys

import psutil

from flm_pipeline.cli import _supervise


def test_timeout_terminates_worker_and_child_process(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    worker_code = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"open({str(child_pid_file)!r},'w',encoding='utf-8').write(str(child.pid)); "
        "time.sleep(30)"
    )

    result = _supervise(
        [sys.executable, "-c", worker_code],
        Path(__file__).resolve().parents[2],
        tmp_path / "timeout.log",
        timeout_seconds=1,
        rss_limit=4 * 1024**3,
    )

    assert result["failure_reason"] == "stage exceeded 1 seconds"
    assert result["child_cleanup_complete"] is True
    assert child_pid_file.is_file()
    assert not psutil.pid_exists(int(child_pid_file.read_text(encoding="utf-8")))


def test_rss_limit_terminates_worker(tmp_path: Path) -> None:
    worker_code = "import time; payload=bytearray(8*1024*1024); time.sleep(30)"

    result = _supervise(
        [sys.executable, "-c", worker_code],
        Path(__file__).resolve().parents[2],
        tmp_path / "rss.log",
        timeout_seconds=30,
        rss_limit=1024,
    )

    assert result["failure_reason"] == "sampled process-tree RSS exceeded 1024 bytes"
    assert result["child_cleanup_complete"] is True

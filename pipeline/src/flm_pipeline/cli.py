"""Command-line checks for the local offline preparation environment."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid

from .config import ConfigError, PipelineConfig, load_config, validate_source_files
from .code_identity import code_identity
from .extractor import ExtractionFailure, load_accepted_inventory, run_extraction, sha256_file, validate_output_directory
from .gpkg_export import export_extraction, export_worker
from .kml_export import build_worker as _earth_build_worker, export_inspection_package
from .inventory import build_inventory, inventory_bytes
from .runtime import environment_errors, runtime_versions


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_state(repo_root: Path) -> dict[str, str | bool | None]:
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=repo_root, check=True, capture_output=True, text=True).stdout.strip())
        return {"revision": revision, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"revision": None, "dirty": True}


def doctor(config_path: Path) -> tuple[int, dict[str, object]]:
    try:
        config = load_config(config_path)
    except ConfigError as error:
        return 1, {"status": "fail", "errors": [str(error)]}
    errors = environment_errors()
    errors.extend(validate_source_files(config))
    report = {
        "status": "fail" if errors else "pass",
        "config_version": config.config_version,
        "region_id": config.region_id,
        "configuration": config.config_path.relative_to(config.repo_root).as_posix(),
        "runtime": runtime_versions(),
        "sources": {
            source_id: {
                "path": source.relative_path,
                "exists": source.path.is_file(),
                "expected_sha256_pinned": source.expected_sha256 is not None,
            }
            for source_id, source in config.sources.items()
        },
        "output_root": config.output_relative_path,
        "configuration_mode": "discovery" if any(source.expected_sha256 is None for source in config.sources.values()) else "pinned",
        "errors": errors,
    }
    return (1 if errors else 0), report


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _promote_directory(source: Path, destination: Path) -> None:
    """Atomically rename on the same volume, retrying transient Windows sharing locks."""
    delays = (0.1, 0.25, 0.5)
    for delay in (*delays, None):
        try:
            os.replace(source, destination)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in {5, 32} or delay is None:
                raise
            time.sleep(delay)


def _kill_tree(process: object) -> list[int]:
    import psutil

    try:
        descendants = process.children(recursive=True)
    except psutil.Error:
        descendants = []
    for child in reversed(descendants):
        try:
            child.kill()
        except psutil.Error:
            pass
    try:
        process.kill()
    except psutil.Error:
        pass
    _, alive = psutil.wait_procs([*descendants, process], timeout=5)
    return [item.pid for item in alive]


def _tree_rss(process: object) -> int:
    import psutil

    processes = [process]
    try:
        processes.extend(process.children(recursive=True))
    except psutil.Error:
        pass
    total = 0
    for item in processes:
        try:
            total += item.memory_info().rss
        except psutil.Error:
            continue
    return total


def _supervise(command: list[str], cwd: Path, log_path: Path, timeout_seconds: int, rss_limit: int) -> dict[str, object]:
    import psutil

    start = time.monotonic()
    peak_rss = 0
    failure_reason = None
    known_children: dict[int, float] = {}
    remaining_process_ids: list[int] = []
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
        monitored = psutil.Process(process.pid)
        while process.poll() is None:
            elapsed = time.monotonic() - start
            try:
                for child in monitored.children(recursive=True):
                    try:
                        known_children[child.pid] = child.create_time()
                    except psutil.Error:
                        continue
            except psutil.Error:
                pass
            peak_rss = max(peak_rss, _tree_rss(monitored))
            if elapsed > timeout_seconds:
                failure_reason = f"stage exceeded {timeout_seconds} seconds"
                remaining_process_ids = _kill_tree(monitored)
                break
            if peak_rss > rss_limit:
                failure_reason = f"sampled process-tree RSS exceeded {rss_limit} bytes"
                remaining_process_ids = _kill_tree(monitored)
                break
            time.sleep(1)
        try:
            exit_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            remaining_process_ids = _kill_tree(monitored)
            exit_code = process.wait(timeout=5)
        if failure_reason is None:
            orphaned: list[object] = []
            for child_pid, created_at in known_children.items():
                try:
                    child = psutil.Process(child_pid)
                    if child.create_time() == created_at and child.is_running():
                        orphaned.append(child)
                except psutil.Error:
                    continue
            if orphaned:
                failure_reason = "worker exited while child processes were still running"
                for child in reversed(orphaned):
                    try:
                        child.kill()
                    except psutil.Error:
                        pass
                _, alive = psutil.wait_procs(orphaned, timeout=5)
                remaining_process_ids = [child.pid for child in alive]
    return {
        "exit_code": exit_code,
        "duration_seconds": round(time.monotonic() - start, 3),
        "sampled_peak_rss_bytes": peak_rss,
        "sample_interval_seconds": 1,
        "rss_limit_bytes": rss_limit,
        "failure_reason": failure_reason,
        "child_cleanup_complete": not remaining_process_ids,
        "remaining_process_ids": remaining_process_ids,
        "log": log_path.name,
    }


def _report_base(config: PipelineConfig, run_id: str, started_at: str) -> dict[str, object]:
    return {
        "report_version": "prototype-run-1",
        "run_id": run_id,
        "started_at_utc": started_at,
        "finished_at_utc": None,
        "status": "running",
        "code": _git_state(config.repo_root),
        "code_identity": code_identity(),
        "configuration": {
            "path": config.config_path.relative_to(config.repo_root).as_posix(),
            "sha256": _sha256(config.config_path),
        },
        "source_inventory_sha256": None,
        "sources": {source_id: {"path": source.relative_path, "expected_sha256": source.expected_sha256} for source_id, source in config.sources.items()},
        "environment": runtime_versions(),
        "platform": platform.platform(),
        "stages": [],
        "input_counts": {},
        "output_counts": {},
        "output_layers": {},
        "output_hashes": {},
        "diagnostics": [],
        "checks": {},
        "rejected_unresolved_ids": [],
        "unresolved_reference_resolution_performed": None,
        "limitations": [],
        "temporary_directory": None,
        "final_directory": None,
    }


def smoke(config_path: Path) -> tuple[int, dict[str, object]]:
    doctor_code, doctor_report = doctor(config_path)
    if doctor_code:
        return 1, {"status": "fail", "phase": "doctor", "doctor": doctor_report}
    config = load_config(config_path)
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(UTC).isoformat()
    final_dir = config.output_root / run_id
    stage_dir = config.repo_root / "data" / "staging" / "prototype" / run_id
    if final_dir.exists() or stage_dir.exists():
        raise FileExistsError(f"Refusing to reuse run directory: {run_id}")
    stage_dir.mkdir(parents=True)
    report = _report_base(config, run_id, started_at)
    report["temporary_directory"] = stage_dir.relative_to(config.repo_root).as_posix()
    report["final_directory"] = final_dir.relative_to(config.repo_root).as_posix()

    result_path = stage_dir / "worker-result.json"
    gpkg_path = stage_dir / "smoke-roundtrip.gpkg"
    log_path = stage_dir / "smoke-worker.log"
    command = [
        sys.executable,
        "-m",
        "flm_pipeline",
        "_smoke-worker",
        "--config",
        str(config.config_path),
        "--result",
        str(result_path),
        "--gpkg",
        str(gpkg_path),
    ]
    supervised = _supervise(command, config.repo_root, log_path, config.limit_seconds, config.limit_rss_bytes)
    stage_record = {"name": "bounded_source_and_geopackage_smoke", "command": command, **supervised}
    report["stages"] = [stage_record]
    report["diagnostics"] = [stage_record["log"]]
    result: dict[str, object] | None = None
    if result_path.is_file():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            report["diagnostics"].append(f"worker result could not be read: {error}")
    if result is not None:
        report["input_counts"] = {
            "pbf_sampled": {name: details["sample_count"] for name, details in result["pbf"]["samples"].items()},
            "census_sampled": {name: details["sample_count"] for name, details in result["census"].items()},
        }
        report["output_counts"] = {name: layer["feature_count"] for name, layer in result["geopackage"]["layers"].items()}
        report["output_layers"] = result["geopackage"]["layers"]
        report["checks"] = result["checks"]
        report["limitations"] = result["limitations"]
    successful = (
        supervised["exit_code"] == 0
        and supervised["failure_reason"] is None
        and result is not None
        and all(result["checks"].values())
        and gpkg_path.is_file()
    )
    if successful:
        final_dir.mkdir(parents=True, exist_ok=False)
        final_gpkg = final_dir / "smoke-roundtrip.gpkg"
        os.replace(gpkg_path, final_gpkg)
        report["output_hashes"] = {"smoke-roundtrip.gpkg": _sha256(final_gpkg)}
    else:
        report["diagnostics"].append(str(supervised["failure_reason"] or f"worker exited with {supervised['exit_code']}"))

    report["status"] = "pass" if successful else "fail"
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    report_path = (final_dir if successful else stage_dir) / "run-report.json"
    _write_json(report_path, report)
    return (0 if successful else 1), {"status": report["status"], "run_id": run_id, "report": report_path.relative_to(config.repo_root).as_posix(), "checks": report["checks"], "diagnostics": report["diagnostics"]}


def inventory(config_path: Path) -> tuple[int, dict[str, object]]:
    """Run the full source inventory under the same deadline and RSS supervisor as smoke."""
    try:
        config = load_config(config_path)
    except ConfigError as error:
        return 1, {"status": "fail", "phase": "configuration", "errors": [str(error)]}
    errors = environment_errors()
    if errors:
        return 1, {"status": "fail", "phase": "environment", "errors": errors}

    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(UTC).isoformat()
    final_dir = config.output_root / run_id
    stage_dir = config.repo_root / "data" / "staging" / "prototype" / run_id
    if final_dir.exists() or stage_dir.exists():
        raise FileExistsError(f"Refusing to reuse run directory: {run_id}")
    stage_dir.mkdir(parents=True)

    result_path = stage_dir / "inventory-worker-result.json"
    log_path = stage_dir / "inventory-worker.log"
    command = [
        sys.executable,
        "-m",
        "flm_pipeline",
        "_inventory-worker",
        "--config",
        str(config.config_path),
        "--result",
        str(result_path),
    ]
    supervised = _supervise(command, config.repo_root, log_path, config.limit_seconds, config.limit_rss_bytes)
    run_report = _report_base(config, run_id, started_at)
    run_report["temporary_directory"] = stage_dir.relative_to(config.repo_root).as_posix()
    run_report["final_directory"] = final_dir.relative_to(config.repo_root).as_posix()
    run_report["stages"] = [{"name": "full_source_inventory", "command": command, **supervised}]
    run_report["diagnostics"] = [log_path.relative_to(config.repo_root).as_posix()]

    worker_result: dict[str, object] | None = None
    if result_path.is_file():
        try:
            worker_result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            run_report["diagnostics"].append(f"Inventory worker result could not be read: {error}")

    inventory_value = worker_result.get("inventory") if worker_result else None
    inventory_path: Path | None = None
    if isinstance(inventory_value, dict):
        source_inventory_bytes = inventory_bytes(inventory_value)
        source_inventory_hash = hashlib.sha256(source_inventory_bytes).hexdigest()
        run_report["source_inventory_sha256"] = source_inventory_hash
        run_report["inventory_status"] = inventory_value.get("inventory_status")
        run_report["input_counts"] = {
            source_id: {
                "bytes": source.get("bytes"),
                "actual_feature_count": source.get("actual_feature_count"),
                "entity_counts": source.get("entity_counts"),
            }
            for source_id, source in inventory_value.get("sources", {}).items()
        }
        run_report["checks"] = {
            source_id: source.get("validation_status")
            for source_id, source in inventory_value.get("sources", {}).items()
        }
        id_findings: list[dict[str, object]] = []
        identifier_issue_types = (
            ("null_count", "null identifier", None),
            ("blank_count", "blank identifier", None),
            ("duplicate_count", "duplicate identifier", "duplicate_examples"),
            ("invalid_width_count", "identifier has an unexpected fixed width", "invalid_examples"),
            ("invalid_format_count", "identifier contains non-digit characters", "invalid_examples"),
        )
        for source_id, source_record in inventory_value.get("sources", {}).items():
            identifier_checks = source_record.get("identifier_checks") or {}
            for check_name, reason, examples_field in identifier_issue_types:
                count = identifier_checks.get(check_name, 0)
                if count:
                    id_findings.append({
                        "source_id": source_id,
                        "check": check_name,
                        "count": count,
                        "reason": reason,
                        "examples": identifier_checks.get(examples_field, []) if examples_field else [],
                        "source_records_modified": False,
                    })
        run_report["rejected_unresolved_ids"] = id_findings
        run_report["unresolved_reference_resolution_performed"] = False
        run_report["limitations"] = inventory_value.get("limitations", [])
        run_report["output_hashes"] = {"source-inventory.json": source_inventory_hash}
        final_dir.mkdir(parents=True, exist_ok=False)
        inventory_path = final_dir / "source-inventory.json"
        inventory_path.write_bytes(source_inventory_bytes)
        run_report["output_counts"] = {"inventory_sources": len(inventory_value.get("sources", {}))}
        run_report["status"] = inventory_value.get("inventory_status", "fail")
        if inventory_value.get("code_identity") != run_report["code_identity"]:
            run_report["status"] = "fail"
            run_report["diagnostics"].append("Pipeline files changed while the inventory worker was running.")
    else:
        run_report["status"] = "fail"
        run_report["limitations"] = ["The inventory worker did not produce a readable source inventory."]
        run_report["diagnostics"].append(str(supervised["failure_reason"] or f"worker exited with {supervised['exit_code']}"))

    if supervised["failure_reason"] is not None or supervised["exit_code"] != 0:
        run_report["status"] = "fail"
        run_report["diagnostics"].append(str(supervised["failure_reason"] or f"worker exited with {supervised['exit_code']}"))
    run_report["finished_at_utc"] = datetime.now(UTC).isoformat()
    report_directory = final_dir if inventory_path else stage_dir
    run_report_path = report_directory / "run-report.json"
    _write_json(run_report_path, run_report)

    return_code = 0 if run_report["status"] in {"pass", "pass_with_warnings"} and supervised["failure_reason"] is None else 1
    return return_code, {
        "status": run_report["status"],
        "run_id": run_id,
        "source_inventory": inventory_path.relative_to(config.repo_root).as_posix() if inventory_path else None,
        "source_inventory_sha256": run_report["source_inventory_sha256"],
        "run_report": run_report_path.relative_to(config.repo_root).as_posix(),
        "checks": run_report["checks"],
        "diagnostics": run_report["diagnostics"],
    }


def extract(config_path: Path, source_inventory_path: Path, inventory_report_path: Path) -> tuple[int, dict[str, object]]:
    """Run a pinned, inventory-linked regional extraction under the worker supervisor."""
    try:
        config = load_config(config_path)
        errors = environment_errors()
        if errors:
            return 1, {"status": "fail", "phase": "environment", "errors": errors}
        inventory_value, _, inventory_hash, inventory_file, inventory_report_file = load_accepted_inventory(
            config, source_inventory_path, inventory_report_path
        )
        initial_config_hash = _sha256(config.config_path)
        initial_code_identity = code_identity()
    except (ConfigError, ExtractionFailure, OSError, ValueError, TypeError) as error:
        return 1, {"status": "fail", "phase": "preflight", "errors": [str(error)]}

    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(UTC).isoformat()
    final_dir = config.output_root / run_id
    stage_dir = config.repo_root / "data" / "staging" / "prototype" / run_id
    candidate_dir = stage_dir / "candidate"
    if final_dir.exists() or stage_dir.exists():
        raise FileExistsError(f"Refusing to reuse run directory: {run_id}")
    stage_dir.mkdir(parents=True)

    result_path = stage_dir / "extract-worker-result.json"
    log_path = stage_dir / "extract-worker.log"
    command = [
        sys.executable,
        "-m",
        "flm_pipeline",
        "_extract-worker",
        "--config",
        str(config.config_path),
        "--source-inventory",
        str(inventory_file),
        "--inventory-report",
        str(inventory_report_file),
        "--candidate",
        str(candidate_dir),
        "--result",
        str(result_path),
        "--run-id",
        run_id,
    ]
    supervised = _supervise(command, config.repo_root, log_path, config.limit_seconds, config.limit_rss_bytes)
    report = _report_base(config, run_id, started_at)
    report.update(
        {
            "temporary_directory": stage_dir.relative_to(config.repo_root).as_posix(),
            "final_directory": final_dir.relative_to(config.repo_root).as_posix(),
            "source_inventory_sha256": inventory_hash,
            "inventory_status": inventory_value.get("inventory_status"),
            "input_counts": {"osm_entities_from_inventory": inventory_value["sources"]["osm"]["entity_counts"]},
            "stages": [{"name": "regional_source_network_extraction", "command": command, **supervised}],
            "diagnostics": [log_path.relative_to(config.repo_root).as_posix()],
            "checks": {
                "inventory_linked": True,
                "source_hash_before_and_after": False,
                "entity_counts_reconciled": False,
                "required_way_references_resolve": False,
                "canonical_outputs_reopened": False,
                "worker_exit_zero": supervised.get("exit_code") == 0,
                "child_cleanup_complete": supervised.get("child_cleanup_complete", True),
            },
        }
    )
    worker_result: dict[str, Any] | None = None
    if result_path.is_file():
        try:
            loaded = json.loads(result_path.read_text(encoding="utf-8"))
            worker_result = loaded if isinstance(loaded, dict) else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            report["diagnostics"].append(f"Extractor worker result could not be read: {error}")

    failure_reason = supervised.get("failure_reason")
    if not supervised.get("child_cleanup_complete", True):
        failure_reason = failure_reason or "worker child process cleanup did not complete"
    if worker_result is None:
        failure_reason = failure_reason or "Extractor worker did not produce a readable result"
    elif worker_result.get("status") not in {"pass", "empty"}:
        worker_error = str(worker_result.get("error") or "Extractor worker reported failure")
        report["diagnostics"].append(worker_error)
        failure_reason = failure_reason or worker_error
        worker_diagnostics = worker_result.get("diagnostics", [])
        report["diagnostics"].extend(worker_diagnostics)
        if isinstance(worker_diagnostics, list):
            report["rejected_unresolved_ids"] = [
                diagnostic
                for diagnostic in worker_diagnostics
                if isinstance(diagnostic, dict) and diagnostic.get("phase") == "required-node-resolution"
            ]
            if report["rejected_unresolved_ids"]:
                report["unresolved_reference_resolution_performed"] = True
    if supervised.get("exit_code") != 0:
        failure_reason = failure_reason or f"worker exited with {supervised.get('exit_code')}"

    expected_status = worker_result.get("status") if worker_result else None
    candidate_metadata: dict[str, Any] | None = None
    if failure_reason is None:
        try:
            metadata = json.loads((candidate_dir / "extraction.json").read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError("extraction.json root must be an object")
            candidate_metadata = metadata
            if metadata.get("status") != expected_status:
                raise ValueError("worker result and extraction metadata statuses do not match")
            if metadata.get("code_identity", {}).get("sha256") != initial_code_identity["sha256"]:
                raise ValueError("pipeline code changed during extraction")
            if _sha256(config.config_path) != initial_config_hash:
                raise ValueError("configuration changed during extraction")
            if _sha256(config.sources["osm"].path).casefold() != (config.sources["osm"].expected_sha256 or "").casefold():
                raise ValueError("OSM source hash changed during extraction")
            if _sha256(inventory_file) != inventory_hash:
                raise ValueError("source inventory changed during extraction")
            if validate_output_directory(candidate_dir) != metadata.get("files"):
                raise ValueError("canonical output validation did not match extraction metadata")
            report["checks"].update(
                {
                    "source_hash_before_and_after": metadata.get("processing", {}).get("source_hash_verified_before_and_after") is True,
                    "entity_counts_reconciled": metadata.get("counts", {}).get("scanned_entities") == inventory_value["sources"]["osm"]["entity_counts"],
                    "required_way_references_resolve": True,
                    "canonical_outputs_reopened": True,
                }
            )
            if not all(report["checks"][key] for key in ("source_hash_before_and_after", "entity_counts_reconciled", "required_way_references_resolve", "canonical_outputs_reopened")):
                raise ValueError("one or more required extraction validations did not pass")
            report["unresolved_reference_resolution_performed"] = True
            metadata["processing"]["resource_supervision"] = {
                "sampled_peak_process_tree_rss_bytes": supervised.get("sampled_peak_rss_bytes"),
                "sample_interval_seconds": supervised.get("sample_interval_seconds", 1),
                "configured_rss_limit_bytes": config.limit_rss_bytes,
                "configured_timeout_seconds": config.limit_seconds,
                "worker_duration_seconds": supervised.get("duration_seconds"),
            }
            report["limitations"] = metadata.get("limitations", [])
            (candidate_dir / "extraction.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
            candidate_metadata = metadata
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, ExtractionFailure) as error:
            failure_reason = f"Candidate validation failed: {error}"

    if failure_reason is None and candidate_metadata is not None:
        try:
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            if final_dir.exists():
                raise FileExistsError(f"Refusing to overwrite extraction destination: {final_dir}")
            if candidate_dir.stat().st_dev != final_dir.parent.stat().st_dev:
                raise OSError("Staging and generated output are not on the same volume")
            report["status"] = "promotion_pending"
            report["output_counts"] = candidate_metadata["counts"]
            report["output_hashes"] = {name: details["sha256"] for name, details in candidate_metadata["files"].items()}
            report["output_hashes"]["extraction.json"] = _sha256(candidate_dir / "extraction.json")
            report["output_hashes"]["code-manifest.json"] = _sha256(candidate_dir / "code-manifest.json")
            report["extraction_status"] = expected_status
            _write_json(candidate_dir / "run-report.json", report)
            _promote_directory(candidate_dir, final_dir)
            if validate_output_directory(final_dir) != candidate_metadata["files"]:
                raise ValueError("promoted canonical output does not match the validated candidate")
            if _sha256(config.sources["osm"].path).casefold() != (config.sources["osm"].expected_sha256 or "").casefold():
                raise ValueError("OSM source changed before promotion verification")
            report["status"] = expected_status
            report["finished_at_utc"] = datetime.now(UTC).isoformat()
            report["final_directory"] = final_dir.relative_to(config.repo_root).as_posix()
            report["output_hashes"]["extraction.json"] = _sha256(final_dir / "extraction.json")
            _write_json(final_dir / "run-report.json", report)
            return 0, {
                "status": expected_status,
                "run_id": run_id,
                "output_directory": final_dir.relative_to(config.repo_root).as_posix(),
                "run_report": (final_dir / "run-report.json").relative_to(config.repo_root).as_posix(),
                "source_inventory_sha256": inventory_hash,
                "output_counts": candidate_metadata["counts"],
                "output_hashes": report["output_hashes"],
                "sampled_peak_rss_bytes": supervised.get("sampled_peak_rss_bytes"),
            }
        except (OSError, ValueError, ExtractionFailure) as error:
            failure_reason = f"Promotion failed: {error}"
            if final_dir.exists() and not candidate_dir.exists():
                try:
                    _promote_directory(final_dir, candidate_dir)
                except OSError:
                    report["diagnostics"].append("Pending candidate remains under generated output because rollback failed.")

    report["status"] = "fail"
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    report["diagnostics"].append(str(failure_reason))
    report_path = stage_dir / "run-report.json"
    _write_json(report_path, report)
    return 1, {
        "status": "fail",
        "run_id": run_id,
        "run_report": report_path.relative_to(config.repo_root).as_posix(),
        "diagnostics": report["diagnostics"],
    }


def _worker(config_path: Path, result_path: Path, gpkg_path: Path) -> int:
    from .smoke_worker import run_worker

    config = load_config(config_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    run_worker(config, result_path, gpkg_path)
    return 0


def _inventory_worker(config_path: Path, result_path: Path) -> int:
    config = load_config(config_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_value = build_inventory(config)
    _write_json(result_path, {"inventory": inventory_value})
    status = inventory_value["inventory_status"]
    return 0 if status in {"pass", "pass_with_warnings"} else 1


def _extract_worker(config_path: Path, inventory_path: Path, inventory_report_path: Path, candidate_path: Path, result_path: Path, run_id: str) -> int:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        config = load_config(config_path)
        result = run_extraction(config, inventory_path, inventory_report_path, run_id, candidate_path)
        _write_json(result_path, result)
        return 0
    except Exception as error:
        _write_json(result_path, {"status": "fail", "error": str(error), "diagnostics": getattr(error, "diagnostics", [])})
        print(f"Extraction failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


def _earth_worker(config_path: Path, extraction_path: Path, gpkg_export_path: Path, candidate_path: Path, result_path: Path, package_id: str, dataset_kind: str, review_profile: str) -> int:
    return _earth_build_worker(config_path, extraction_path, gpkg_export_path, candidate_path, result_path, package_id, dataset_kind, review_profile)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m flm_pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("doctor", "smoke", "inventory"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--config", type=Path, required=True)
    classify_parser = subparsers.add_parser("classify", help="Classify a verified source extraction under pedestrian-policy-0.3")
    classify_parser.add_argument("--extraction", type=Path, required=True)
    classify_parser.add_argument("--policy-config", type=Path, default=Path("pipeline/config/pedestrian-policy.example.toml"))
    classify_parser.add_argument("--output-root", type=Path)
    for graph_command in ("graph", "_graph-worker"):
        graph_parser = subparsers.add_parser(graph_command, help="Assemble and validate an experimental directed graph")
        graph_parser.add_argument("--extraction", type=Path, required=True)
        graph_parser.add_argument("--classification", type=Path, required=True)
        graph_parser.add_argument("--policy-config", type=Path, default=Path("pipeline/config/pedestrian-policy.example.toml"))
        if graph_command == "graph":
            graph_parser.add_argument("--output-root", type=Path)
        else:
            graph_parser.add_argument("--stage", type=Path, required=True)
            graph_parser.add_argument("--result", type=Path, required=True)
    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("--config", type=Path, required=True)
    extract_parser.add_argument("--source-inventory", type=Path, required=True)
    extract_parser.add_argument("--inventory-report", type=Path, required=True)
    export_parser = subparsers.add_parser("export", help="Export an accepted regional extraction to source-network.gpkg")
    export_parser.add_argument("--config", type=Path, required=True)
    export_parser.add_argument("--extraction", type=Path, required=True)
    export_worker_parser = subparsers.add_parser("_export-worker", help=argparse.SUPPRESS)
    export_worker_parser.add_argument("--config", type=Path, required=True)
    export_worker_parser.add_argument("--extraction", type=Path, required=True)
    export_worker_parser.add_argument("--run-id", required=True)
    export_worker_parser.add_argument("--stage", type=Path, required=True)
    export_worker_parser.add_argument("--result", type=Path, required=True)
    earth_parser = subparsers.add_parser("earth-export", help="Export a validated source-network inspection package for Google Earth")
    earth_parser.add_argument("--config", type=Path, required=True)
    earth_parser.add_argument("--extraction", type=Path, required=True)
    earth_parser.add_argument("--gpkg-export", type=Path, required=True)
    earth_parser.add_argument("--dataset-kind", choices=("synthetic", "regional"), required=True)
    earth_parser.add_argument("--review-profile", choices=("topology", "diagnostic", "regional"))
    worker_parser = subparsers.add_parser("_smoke-worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("--config", type=Path, required=True)
    worker_parser.add_argument("--result", type=Path, required=True)
    worker_parser.add_argument("--gpkg", type=Path, required=True)
    inventory_worker_parser = subparsers.add_parser("_inventory-worker", help=argparse.SUPPRESS)
    inventory_worker_parser.add_argument("--config", type=Path, required=True)
    inventory_worker_parser.add_argument("--result", type=Path, required=True)
    extract_worker_parser = subparsers.add_parser("_extract-worker", help=argparse.SUPPRESS)
    extract_worker_parser.add_argument("--config", type=Path, required=True)
    extract_worker_parser.add_argument("--source-inventory", type=Path, required=True)
    extract_worker_parser.add_argument("--inventory-report", type=Path, required=True)
    extract_worker_parser.add_argument("--candidate", type=Path, required=True)
    extract_worker_parser.add_argument("--result", type=Path, required=True)
    extract_worker_parser.add_argument("--run-id", required=True)
    earth_worker_parser = subparsers.add_parser("_earth-worker", help=argparse.SUPPRESS)
    earth_worker_parser.add_argument("--config", type=Path, required=True)
    earth_worker_parser.add_argument("--extraction", type=Path, required=True)
    earth_worker_parser.add_argument("--gpkg-export", type=Path, required=True)
    earth_worker_parser.add_argument("--candidate", type=Path, required=True)
    earth_worker_parser.add_argument("--result", type=Path, required=True)
    earth_worker_parser.add_argument("--package-id", required=True)
    earth_worker_parser.add_argument("--dataset-kind", choices=("synthetic", "regional"), required=True)
    earth_worker_parser.add_argument("--review-profile", choices=("topology", "diagnostic", "regional"), required=True)
    census_parser = subparsers.add_parser("census-sample", help="Fetch and validate the approved local Census sample")
    census_parser.add_argument("--config", type=Path, required=True)
    census_worker_parser = subparsers.add_parser("_census-worker", help=argparse.SUPPRESS)
    census_worker_parser.add_argument("--config", type=Path, required=True)
    census_worker_parser.add_argument("--stage", type=Path, required=True)
    census_worker_parser.add_argument("--result", type=Path, required=True)
    census_worker_parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"census-sample", "_census-worker"}:
            from .census_sample import census_sample_worker, run_census_sample

            if args.command == "_census-worker":
                return census_sample_worker(args.config, args.stage, args.result, args.run_id)
            code, report = run_census_sample(args.config)
        elif args.command in {"graph", "_graph-worker"}:
            from .graph import build_graph, run_graph

            if args.command == "_graph-worker":
                report = build_graph(args.extraction, args.classification, args.policy_config, args.stage, lambda message: print(message, flush=True))
                _write_json(args.result, report)
                return 0
            code, report = run_graph(args.extraction, args.classification, args.policy_config, args.output_root)
        elif args.command == "classify":
            from .classification import run_classification

            def progress(message: str) -> None:
                print(message, file=sys.stderr)

            code, report = run_classification(args.extraction, args.policy_config, args.output_root, progress)
        elif args.command == "doctor":
            code, report = doctor(args.config)
        elif args.command == "smoke":
            code, report = smoke(args.config)
        elif args.command == "inventory":
            code, report = inventory(args.config)
        elif args.command == "extract":
            code, report = extract(args.config, args.source_inventory, args.inventory_report)
        elif args.command == "export":
            code, report = export_extraction(args.config, args.extraction)
        elif args.command == "_export-worker":
            return export_worker(args.config, args.extraction, args.run_id, args.stage, args.result)
        elif args.command == "earth-export":
            review_profile = args.review_profile or ("regional" if args.dataset_kind == "regional" else "topology")
            code, report = export_inspection_package(args.config, args.extraction, args.gpkg_export, args.dataset_kind, review_profile)
        elif args.command == "_earth-worker":
            return _earth_worker(args.config, args.extraction, args.gpkg_export, args.candidate, args.result, args.package_id, args.dataset_kind, args.review_profile)
        elif args.command == "_inventory-worker":
            return _inventory_worker(args.config, args.result)
        elif args.command == "_extract-worker":
            return _extract_worker(args.config, args.source_inventory, args.inventory_report, args.candidate, args.result, args.run_id)
        else:
            return _worker(args.config, args.result, args.gpkg)
    except (ConfigError, OSError, RuntimeError, ValueError) as error:
        code, report = 1, {"status": "fail", "errors": [str(error)]}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

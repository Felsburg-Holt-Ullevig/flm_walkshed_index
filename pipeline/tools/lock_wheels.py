"""Build Windows Python locks and a wheel-license inventory from downloaded wheels."""

from __future__ import annotations

import argparse
from email.parser import Parser
import hashlib
from pathlib import Path
import re
from zipfile import ZipFile


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def inspect_wheel(path: Path) -> dict[str, str]:
    with ZipFile(path) as wheel:
        metadata_name = next(name for name in wheel.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(wheel.read(metadata_name).decode("utf-8", errors="replace"))
        license_value = metadata.get("License-Expression")
        if not license_value:
            license_value = (metadata.get("License") or "UNSPECIFIED").strip().splitlines()[0]
        license_value = " ".join(license_value.strip().split())
        license_files = [
            name.split(".dist-info/licenses/", 1)[1]
            for name in wheel.namelist()
            if ".dist-info/licenses/" in name and not name.endswith("/")
        ]
        native_binaries = [
            name
            for name in wheel.namelist()
            if name.lower().endswith((".dll", ".pyd", ".so", ".dylib"))
        ]
        return {
            "name": metadata["Name"],
            "version": metadata["Version"],
            "normalized_name": _normalize(metadata["Name"]),
            "license": license_value.splitlines()[0],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "license_files": ", ".join(license_files[:5]) + (f" (+{len(license_files) - 5} more)" if len(license_files) > 5 else ""),
            "native_binaries": ", ".join(native_binaries),
        }


def write_lock(path: Path, wheels: list[dict[str, str]], header: str) -> None:
    lines = [header, ""]
    for wheel in sorted(wheels, key=lambda item: item["normalized_name"]):
        lines.append(f"{wheel['name']}=={wheel['version']} \\")
        lines.append(f"    --hash=sha256:{wheel['sha256']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--lock-output", type=Path, required=True)
    parser.add_argument("--pip-lock-output", type=Path, required=True)
    parser.add_argument("--license-output", type=Path, required=True)
    args = parser.parse_args()
    wheels = [inspect_wheel(path) for path in sorted(args.wheel_dir.glob("*.whl"))]
    if not wheels:
        parser.error("wheel directory contains no .whl files")
    names = [wheel["normalized_name"] for wheel in wheels]
    if len(set(names)) != len(names):
        parser.error("wheel directory contains more than one wheel for a distribution")
    pip_wheels = [wheel for wheel in wheels if wheel["normalized_name"] == "pip"]
    app_wheels = [wheel for wheel in wheels if wheel["normalized_name"] != "pip"]
    if len(pip_wheels) != 1 or not app_wheels:
        parser.error("expected exactly one pip wheel and at least one application dependency wheel")

    write_lock(args.lock_output, app_wheels, "# Windows x86-64, CPython 3.12.14; exact wheel versions and SHA-256 hashes.")
    write_lock(args.pip_lock_output, pip_wheels, "# Windows x86-64, CPython 3.12.14; pip bootstrap wheel.")
    license_lines = [
        "# Python wheel license inventory",
        "",
        "Target: Windows x86-64, CPython 3.12.14. License values come from each downloaded wheel's METADATA; listed license files are included in that wheel.",
        "This inventory records Python distributions and bundled license files. Native runtime versions are reported separately by `doctor`; review any new wheel or bundled native component before adopting a later lock.",
        "",
        "| Distribution | Version | Wheel license metadata | Included license files |",
        "|---|---:|---|---|",
    ]
    for wheel in sorted(wheels, key=lambda item: item["normalized_name"]):
        license_lines.append(
            f"| {wheel['name']} | {wheel['version']} | {wheel['license'].replace('|', '\\|')} | {wheel['license_files'] or 'No separate license file'} |"
        )
    license_lines.extend([
        "",
        "## Bundled native binary files",
        "",
        "These filenames come from the exact wheel archives used to build the lock. Their runtime versions and known upstream license terms are summarized in `environment-win-py312.md`.",
        "",
        "| Distribution | Native binary files |",
        "|---|---|",
    ])
    for wheel in sorted(wheels, key=lambda item: item["normalized_name"]):
        if wheel["native_binaries"]:
            binaries = wheel["native_binaries"].replace("|", "\\|")
            license_lines.append(f"| {wheel['name']} {wheel['version']} | `{binaries}` |")
    args.license_output.write_text("\n".join(license_lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(app_wheels)} dependency pins and {len(wheels)} license records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

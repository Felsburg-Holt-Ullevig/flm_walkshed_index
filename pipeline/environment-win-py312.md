# Offline Python environment

The offline preparation package targets Windows x86-64 and CPython 3.12.14. `doctor` checks the runtime. The `.venv/` environment is ignored by Git; package versions and wheel hashes are recorded in [`requirements-win-py312.lock.txt`](requirements-win-py312.lock.txt), Task 5.2 adds the complete schema-validator dependency set in [`requirements-package-win-py312.lock.txt`](requirements-package-win-py312.lock.txt), and the pip bootstrap is separately pinned in [`requirements-bootstrap-win-py312.lock.txt`](requirements-bootstrap-win-py312.lock.txt).

## Create the environment

Use an explicit installed Python executable:

```powershell
.\pipeline\bootstrap.ps1 -BasePythonPath 'C:\path\to\python.exe'
```

The script creates `.venv/`, installs pip 26.2.2 with `--require-hashes --only-binary=:all:`, installs the locked dependencies with the same checks, installs the local package without resolving dependencies again, and runs `doctor`. It stops if `.venv/` already exists so that recreating an environment is an explicit operation. To verify recreation, use a second ignored environment path and the same lock files, then run `doctor`, `smoke`, and pytest with that environment's `python.exe`.

## Resolve or refresh the lock

The following commands resolve the core preparation wheel set. Task 5.2 resolves the Draft 2020-12 validator separately from `requirements-package.in` and records that exact wheel set in `requirements-package-win-py312.lock.txt`; do not rewrite the core lock when updating that supplemental set. Wheel files are downloaded to a temporary directory and inspected locally; do not install packages into the bundled base runtime.

```powershell
$wheelDir = Join-Path $env:TEMP 'flm-pipeline-wheel-resolution'
New-Item -ItemType Directory -Force -Path $wheelDir | Out-Null
& $basePython -m pip download --only-binary=:all: --dest $wheelDir -r pipeline/requirements.in
& $basePython -m pip download --only-binary=:all: --no-deps --dest $wheelDir pip==26.2.2
& $basePython pipeline/tools/lock_wheels.py `
    --wheel-dir $wheelDir `
    --lock-output pipeline/requirements-win-py312.lock.txt `
    --pip-lock-output pipeline/requirements-bootstrap-win-py312.lock.txt `
    --license-output pipeline/licenses-win-py312.md
```

Set `$basePython` to the explicitly selected CPython 3.12.14 executable before running these commands. `requirements.in` identifies direct preparation packages; the generated lock includes the complete resolved graph with one exact compatible wheel and SHA-256 hash per distribution. A different Python patch version or platform requires a separate resolution and lock.

## Resolved versions

Resolution completed on November 2, 2026 from compatible Windows wheels. Exact package license metadata and included license-file paths are in [`licenses-win-py312.md`](licenses-win-py312.md).

| Purpose | Distribution versions |
|---|---|
| Direct GIS/source packages | `osmium 4.3.2`, `geopandas 1.2.0`, `pandas 3.1.0`, `shapely 2.2.0`, `pyproj 3.8.0`, `pyogrio 0.13.0`, `pytest 9.2.0`, `psutil 7.2.2` |
| Build support | `setuptools 80.9.0`, `pip 26.2.2` |
| Package schema validation | `jsonschema 4.25.1`, plus separately locked `attrs`, `jsonschema-specifications`, `referencing`, `rpds-py`, and `typing-extensions` |
| Transitive dependencies | `certifi 2026.10.23`, `charset-normalizer 3.5.2`, `colorama 0.4.6`, `idna 3.20`, `iniconfig 2.3.1`, `numpy 2.5.4`, `packaging 26.3`, `pluggy 1.7.0`, `Pygments 2.21.0`, `python-dateutil 4.0.0`, `requests 2.34.2`, `tzdata 2026.6`, `urllib3 2.8.0` |

The selected wheels include compiled GIS components. `doctor` observed GDAL 3.12.4, PROJ 9.8.1, and GEOS 3.14.1 on this installation. The Python wheel license metadata, included license files, and exact `.dll`/`.pyd` paths from the selected wheels are recorded in [`licenses-win-py312.md`](licenses-win-py312.md). The native components relevant to this smoke environment are:

| Component | Observed version | License evidence |
|---|---:|---|
| GDAL/OGR through Pyogrio | 3.12.4 | GDAL source is generally MIT; the project notes that optional dependencies and drivers can carry separate terms. Review the full built wheel before redistribution. [GDAL license](https://gdal.org/en/stable/license.html) |
| PROJ through PyProj | 9.8.1 | MIT/X/MIT; the PyProj wheel contains `LICENSE_proj`. [PROJ license](https://proj.org/en/stable/about.html) |
| GEOS through Shapely | 3.14.1 | LGPL; the Shapely wheel contains `LICENSE_GEOS`. [GEOS license](https://libgeos.org/) |
| libosmium through PyOsmium | Version not exposed by the installed module | PyOsmium 4.3.2 is based on libosmium. Upstream libosmium uses the Boost Software License; the Python wheel inventory records PyOsmium's own BSD-2-Clause license. Confirm the bundled native component inventory during task 1.4. [PyOsmium](https://docs.osmcode.org/pyosmium/latest/), [libosmium license](https://docs.osmcode.org/libosmium/latest/) |

PyOsmium reads OSM data through its [`FileProcessor` stream](https://docs.osmcode.org/pyosmium/latest/reference/File-Processing/), while Pyogrio supports [bounded feature reads](https://pyogrio.readthedocs.io/en/latest/api.html) and the GeoPackage driver. This environment does not provide an Osmium command-line executable. The wheel/license inventory describes this prototype installation and is not a redistribution approval.

## Verification completed

Both the repository `.venv/` and a second temporary environment recreated from the same verified wheel cache passed `doctor`, the real-data smoke, and pytest. The second environment passed the nine tests present at that point. After adding an invalid-CRS fixture, the final repository environment passed all ten tests. The final smoke sampled 20 PBF nodes, ways, and relations; five features from each Census archive; and round-tripped one point, line, and polygon layer. This does not establish full-source integrity, statewide performance, or routing completeness.

## Commands

Run from the repository root in PowerShell:

```powershell
& .\.venv\Scripts\python.exe -m flm_pipeline doctor --config pipeline/config/denver-source.example.toml
& .\.venv\Scripts\python.exe -m flm_pipeline smoke --config pipeline/config/denver-source.example.toml
& .\.venv\Scripts\python.exe -m pytest pipeline/tests
```

`doctor` validates the supported runtime, installed packages, strict TOML settings, source-file presence, and output separation. `smoke` samples PBF node, way, and relation streams; reads a bounded feature sample from each Census archive; writes and reopens node, line, and polygon GeoPackage layers; records a JSON run report; and enforces the configured timeout and sampled process-tree RSS limit. This is source-I/O evidence only. Full file hashes, archive CRC checks, counts, and provenance remain part of task 1.3.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $BasePythonPath
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$resolvedPython = (Resolve-Path -LiteralPath $BasePythonPath).Path
$venvPath = Join-Path $repoRoot '.venv'
$venvPython = Join-Path $venvPath 'Scripts/python.exe'

if (-not (Test-Path -LiteralPath $resolvedPython -PathType Leaf)) {
    throw "Base Python executable not found: $resolvedPython"
}

& $resolvedPython --version
if ($LASTEXITCODE -ne 0) { throw 'Base Python could not run.' }
$runtimeCheck = 'import platform, sys; sys.exit(0 if sys.implementation.name == "cpython" and sys.version_info[:3] == (3, 12, 14) and platform.system() == "Windows" and platform.machine().lower() in ("amd64", "x86_64") else 1)'
& $resolvedPython -c $runtimeCheck
if ($LASTEXITCODE -ne 0) { throw 'Base Python must be CPython 3.12.14 on Windows x86-64.' }
if (Test-Path -LiteralPath $venvPath) {
    throw "Environment already exists at $venvPath. Remove it explicitly before recreating."
}

& $resolvedPython -m venv $venvPath
if ($LASTEXITCODE -ne 0) { throw 'Could not create the repository virtual environment.' }

& $venvPython -m pip install --require-hashes --only-binary=:all: -r (Join-Path $PSScriptRoot 'requirements-bootstrap-win-py312.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install the hash-verified pip bootstrap version.' }

& $venvPython -m pip install --require-hashes --only-binary=:all: -r (Join-Path $PSScriptRoot 'requirements-win-py312.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install the locked pipeline dependencies.' }

& $venvPython -m pip install --require-hashes --only-binary=:all: -r (Join-Path $PSScriptRoot 'requirements-package-win-py312.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install the locked package-schema validator.' }

& $venvPython -m pip install --no-deps --no-build-isolation --editable $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Could not install the pipeline package.' }

& $venvPython -m flm_pipeline doctor --config pipeline/config/denver-source.example.toml
if ($LASTEXITCODE -ne 0) { throw 'Environment doctor check failed.' }

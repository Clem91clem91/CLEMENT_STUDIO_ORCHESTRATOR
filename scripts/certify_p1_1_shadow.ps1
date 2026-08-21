$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$ScriptFile = $PSCommandPath
if ([string]::IsNullOrWhiteSpace($ScriptFile)) {
    $ScriptFile = $MyInvocation.MyCommand.Path
}
if ([string]::IsNullOrWhiteSpace($ScriptFile)) {
    throw "P1_1_SCRIPT_PATH_UNRESOLVED"
}

$ScriptDirectory = Split-Path -Path $ScriptFile -Parent
$RepoRoot = Split-Path -Path $ScriptDirectory -Parent
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

Write-Host "============================================================"
Write-Host "CLEMENT STUDIO - P1.1 SHADOW CERTIFICATION"
Write-Host "MODE=FAIL_CLOSED"
Write-Host "ROOT=$RepoRoot"
Write-Host "============================================================"

Push-Location $RepoRoot
try {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "P1_1_VENV_CREATE_FAILED" }
    }

    & $Python -m pip install -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { throw "P1_1_INSTALL_FAILED" }
    Write-Host "INSTALL=PASS"

    & $Python -m compileall -q src tests scripts
    if ($LASTEXITCODE -ne 0) { throw "P1_1_COMPILE_FAILED" }
    Write-Host "COMPILE=PASS"

    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "P1_1_PYTEST_FAILED" }
    Write-Host "PYTEST=PASS"

    & $Python scripts\certify_p1_1_reference.py
    if ($LASTEXITCODE -ne 0) { throw "P1_1_REFERENCE_FAILED" }

    & $Python scripts\certify_p1_1_shadow.py
    if ($LASTEXITCODE -ne 0) { throw "P1_1_SHADOW_REAL_FAILED" }

    Write-Host "============================================================"
    Write-Host "P1_1_01_RAW_EVIDENCE=PASS"
    Write-Host "P1_1_02_PROVENANCE=PASS"
    Write-Host "P1_1_03_CONSISTENCY=PASS"
    Write-Host "P1_1_04_FAIL_CLOSED_VERIFIER=PASS"
    Write-Host "P1_1_SHADOW_REAL=PASS"
    Write-Host "P1_1_GLOBAL=PASS"
    Write-Host "MERGE_EXECUTED=NO"
    Write-Host "TAG_CREATED=NO"
    Write-Host "RELEASE_CREATED=NO"
    Write-Host "NEXT=P1_1_MERGE_VALIDATION"
    Write-Host "============================================================"
}
finally {
    Pop-Location
}

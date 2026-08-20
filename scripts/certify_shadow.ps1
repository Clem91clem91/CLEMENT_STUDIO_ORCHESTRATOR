$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo ".venv\Scripts\python.exe"

Write-Host "============================================================"
Write-Host "CLEMENT - P0-04 ORCHESTRATOR SHADOW CERTIFICATION"
Write-Host "============================================================"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "VENV_PYTHON_NOT_FOUND=$Python"
}

Push-Location $Repo
try {
    if (@(& git status --porcelain).Count -gt 0) {
        throw "WORKTREE_NOT_CLEAN"
    }

    Write-Host "BRANCH=$((& git branch --show-current).Trim())"
    Write-Host "HEAD=$((& git rev-parse HEAD).Trim())"

    & $Python -m compileall -q src tests scripts
    if ($LASTEXITCODE -ne 0) { throw "COMPILE_FAILED" }
    Write-Host "COMPILE=PASS"

    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "PYTEST_FAILED" }
    Write-Host "PYTEST=PASS"

    & $Python scripts\certify_shadow.py
    if ($LASTEXITCODE -ne 0) { throw "ORCHESTRATOR_SMOKE_FAILED" }
    Write-Host "ORCHESTRATOR_SMOKE=PASS"

    Write-Host "MERGE_EXECUTED=NO"
    Write-Host "TAG_CREATED=NO"
    Write-Host "RELEASE_CREATED=NO"
}
finally {
    Pop-Location
}

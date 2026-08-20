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
    $Status = @(& git status --porcelain)
    if ($Status.Count -gt 0) {
        Write-Host "WORKTREE_DIRTY_BEGIN"
        foreach ($Line in $Status) { Write-Host $Line }
        Write-Host "WORKTREE_DIRTY_END"
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

    $AfterStatus = @(& git status --porcelain)
    if ($AfterStatus.Count -eq 0) {
        Write-Host "WORKTREE_AFTER=CLEAN"
    }
    else {
        Write-Host "WORKTREE_AFTER=DIRTY"
        foreach ($Line in $AfterStatus) { Write-Host $Line }
    }

    Write-Host "MERGE_EXECUTED=NO"
    Write-Host "TAG_CREATED=NO"
    Write-Host "RELEASE_CREATED=NO"
}
finally {
    Pop-Location
}

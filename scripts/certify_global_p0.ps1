$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$ExpectedBranch = "feat/p0-dynamic-orchestrator"

Write-Host "============================================================"
Write-Host "CLEMENT STUDIO - GLOBAL P0 CERTIFICATION"
Write-Host "MODE=REAL_E2E_FAIL_CLOSED_SEPARATED_GATES"
Write-Host "============================================================"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "VENV_PYTHON_NOT_FOUND=$Python"
}

Push-Location $Repo
try {
    $Branch = (& git branch --show-current).Trim()
    $Head = (& git rev-parse HEAD).Trim()
    $Status = @(& git status --porcelain)

    Write-Host "P0_04_BRANCH=$Branch"
    Write-Host "P0_04_HEAD=$Head"

    if ($Branch -ne $ExpectedBranch) {
        throw "P0_04_WRONG_BRANCH=$Branch"
    }

    if ($Status.Count -gt 0) {
        Write-Host "WORKTREE_DIRTY_BEGIN"
        foreach ($Line in $Status) { Write-Host $Line }
        Write-Host "WORKTREE_DIRTY_END"
        throw "P0_04_WORKTREE_NOT_CLEAN"
    }

    & $Python -c "import mcp; print('MCP_RUNTIME=PASS')"
    if ($LASTEXITCODE -ne 0) {
        throw "MCP_RUNTIME_MISSING_RUN_PIP_INSTALL_EDITABLE"
    }

    & $Python -m compileall -q src tests scripts
    if ($LASTEXITCODE -ne 0) {
        throw "COMPILE_FAILED"
    }
    Write-Host "COMPILE=PASS"

    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) {
        throw "PYTEST_FAILED"
    }
    Write-Host "PYTEST=PASS"

    & $Python scripts\certify_global_p0_v2.py
    if ($LASTEXITCODE -ne 0) {
        throw "GLOBAL_P0_CERTIFICATION_FAILED"
    }

    $AfterStatus = @(& git status --porcelain)
    if ($AfterStatus.Count -ne 0) {
        Write-Host "WORKTREE_AFTER_DIRTY_BEGIN"
        foreach ($Line in $AfterStatus) { Write-Host $Line }
        Write-Host "WORKTREE_AFTER_DIRTY_END"
        throw "P0_04_WORKTREE_CHANGED_BY_CERTIFICATION"
    }

    Write-Host "WORKTREE_AFTER=CLEAN"
    Write-Host "MERGE_EXECUTED=NO"
    Write-Host "TAG_CREATED=NO"
    Write-Host "RELEASE_CREATED=NO"
}
finally {
    Pop-Location
}

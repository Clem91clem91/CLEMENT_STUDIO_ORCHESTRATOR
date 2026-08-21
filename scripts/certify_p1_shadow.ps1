param()

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Path $PSScriptRoot -Parent
Set-Location $Repo

Write-Host "============================================================"
Write-Host "CLEMENT STUDIO - P1 SHADOW CERTIFICATION"
Write-Host "MODE=REAL_E2E_FAIL_CLOSED"
Write-Host "============================================================"

$Branch = (& git branch --show-current).Trim()
$Head = (& git rev-parse HEAD).Trim()
$Dirty = @(& git status --porcelain)
Write-Host "BRANCH=$Branch"
Write-Host "HEAD=$Head"
Write-Host "DIRTY_COUNT=$($Dirty.Count)"
if ($Branch -ne "feat/p1-execution-core") { throw "P1_WRONG_BRANCH=$Branch" }
if ($Dirty.Count -gt 0) { $Dirty | ForEach-Object { Write-Host $_ }; throw "P1_WORKTREE_NOT_CLEAN" }

$VenvPython = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "P1_VENV_CREATE_FAILED" }
}
& $VenvPython -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "P1_INSTALL_FAILED" }
Write-Host "INSTALL=PASS"
& $VenvPython -m compileall -q src tests scripts
if ($LASTEXITCODE -ne 0) { throw "P1_COMPILE_FAILED" }
Write-Host "COMPILE=PASS"
& $VenvPython -m pytest
if ($LASTEXITCODE -ne 0) { throw "P1_PYTEST_FAILED" }
Write-Host "PYTEST=PASS"
& $VenvPython scripts\certify_p1_reference.py
if ($LASTEXITCODE -ne 0) { throw "P1_REFERENCE_FAILED" }
Write-Host "REFERENCE_E2E=PASS"

$env:CLEMENT_ALLOW_POWERSHELL = "1"
try {
    & $VenvPython scripts\certify_p1_shadow.py
    if ($LASTEXITCODE -ne 0) { throw "P1_REAL_E2E_FAILED" }
}
finally { Remove-Item Env:\CLEMENT_ALLOW_POWERSHELL -ErrorAction SilentlyContinue }

$AfterHead = (& git rev-parse HEAD).Trim()
$AfterDirty = @(& git status --porcelain)
if ($AfterHead -ne $Head) { throw "P1_HEAD_CHANGED_DURING_CERT" }
if ($AfterDirty.Count -gt 0) { $AfterDirty | ForEach-Object { Write-Host $_ }; throw "P1_WORKTREE_CHANGED_DURING_CERT" }

Write-Host "============================================================"
Write-Host "P1_01=PASS"
Write-Host "P1_02=PASS"
Write-Host "P1_03=PASS"
Write-Host "P1_04=PASS"
Write-Host "P1_GLOBAL=PASS"
Write-Host "WORKTREE_AFTER=CLEAN"
Write-Host "MERGE_EXECUTED=NO"
Write-Host "TAG_CREATED=NO"
Write-Host "RELEASE_CREATED=NO"
Write-Host "NEXT=P1_MERGE_VALIDATION"
Write-Host "============================================================"

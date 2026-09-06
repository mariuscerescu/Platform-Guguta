# Guguță verification pipeline (GHID §12.3): lint -> typecheck -> tests -> build.
# Exit code non-zero on any failure. Never reports success on truncation.

param(
    [switch]$SkipBuild,
    [switch]$SkipUpstream
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$uv = "C:\Users\User\AppData\Local\Programs\Python\Python311\Scripts\uv.exe"
if (Get-Command uv -ErrorAction SilentlyContinue) { $uv = "uv" }

Write-Host "== 1/4 Ruff =="
& $uv run ruff check open_notebook/database/guguta open_notebook/auth/guguta api/services/guguta api/routers/guguta_v1.py api/guguta_app.py alembic tests/guguta
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== 2/4 Mypy (pachetul Guguță) =="
& $uv run mypy open_notebook/database/guguta open_notebook/auth/guguta api/services/guguta api/routers/guguta_v1.py api/guguta_app.py tests/guguta
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== 3/4 Teste Guguță PostgreSQL (migrări + RLS) =="
& $uv run pytest tests/guguta -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipUpstream) {
    Write-Host "== 3b/4 Teste upstream (neafectate de fundație) =="
    & $uv run pytest tests/ -q --ignore=tests/guguta
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $SkipBuild) {
    Write-Host "== 4/4 Build frontend =="
    Push-Location frontend
    npm run build
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { exit $code }
}

Write-Host "Toate verificările au trecut."

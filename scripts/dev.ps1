# Guguță local development environment (GHID §12.3).
# Starts ONLY the Guguță stack (PostgreSQL + migrator) — never touches the
# upstream demo volumes. Then verifies services and reports status.
#
# Usage: powershell -File scripts/dev.ps1 [-SkipMigrate]

param(
    [switch]$SkipMigrate
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Assert-Cmd($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        Write-Error "Comanda '$name' lipsește. Instaleaz-o înainte de a continua."
    }
}

Assert-Cmd docker
Write-Host "== Guguță dev: pornire stack PostgreSQL =="

docker compose -f docker-compose.guguta.yml --project-name guguta up -d db
if ($LASTEXITCODE -ne 0) { Write-Error "docker compose db a eșuat" }

Write-Host "Aștept healthcheck db..."
$dbHealthy = $false
for ($i = 0; $i -lt 30; $i++) {
    $status = docker inspect --format "{{.State.Health.Status}}" guguta-db-1 2>$null
    if ($status -eq "healthy") { $dbHealthy = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $dbHealthy) { Write-Error "db nu a devenit healthy la timp" }
Write-Host "db: healthy (PostgreSQL 17 + pgvector pe 127.0.0.1:5433)"

if (-not $SkipMigrate) {
    Write-Host "== Migrare (o singură dată pe release, ADR-0007) =="
    docker compose -f docker-compose.guguta.yml --project-name guguta run --rm migrator
    if ($LASTEXITCODE -ne 0) { Write-Error "migrator a eșuat" }
}

Write-Host "== Verificare extensie pgvector =="
docker compose -f docker-compose.guguta.yml --project-name guguta exec -T db psql -U guguta_migrator -d guguta -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
if ($LASTEXITCODE -ne 0) { Write-Error "pgvector indisponibil" }

Write-Host ""
Write-Host "Guguță dev este pornit. API/worker/frontend se leagă în livrările L2+."
Write-Host "Stop: docker compose -f docker-compose.guguta.yml --project-name guguta down"

param(
    [ValidateSet("start", "stop")][string]$Action = "start",
    [string]$Bin = "C:\Program Files\PostgreSQL\18\bin"
)
$ErrorActionPreference = "Stop"
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$runtime = Join-Path $workspace ".test-runtime"
$data = Join-Path $runtime "postgres-data"
$marker = Join-Path $runtime "AQUAMONITOR_DISPOSABLE_CLUSTER"
if (-not (Test-Path -LiteralPath (Join-Path $Bin "pg_ctl.exe"))) {
    throw "No se encuentra PostgreSQL. Indica -Bin con sus binarios locales."
}
if ((Test-Path -LiteralPath (Join-Path $data "PG_VERSION")) -and -not (Test-Path -LiteralPath $marker)) {
    throw "Clúster sin marca de pruebas. No se iniciará ni detendrá."
}
if ($Action -eq "stop") {
    if (-not (Test-Path -LiteralPath $marker)) { throw "No existe el clúster de pruebas marcado." }
    & (Join-Path $Bin "pg_ctl.exe") -D $data -m fast -w stop
    if ($LASTEXITCODE -ne 0) { throw "No se pudo detener el clúster de pruebas." }
    exit
}
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $data "PG_VERSION"))) {
    & (Join-Path $Bin "initdb.exe") -D $data -U aquamonitor_test -A trust --encoding=UTF8 --no-locale
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el clúster local." }
    Set-Content -LiteralPath $marker -Value "Disposable local test data only" -Encoding ascii
}
& (Join-Path $Bin "pg_ctl.exe") -D $data status
if ($LASTEXITCODE -eq 0) { Write-Output "El clúster local de pruebas ya está activo."; exit }
& (Join-Path $Bin "pg_ctl.exe") -D $data -l (Join-Path $runtime "postgres.log") -o "-h 127.0.0.1 -p 55439" -w start
if ($LASTEXITCODE -ne 0) { throw "No se pudo iniciar el clúster local en 127.0.0.1:55439." }

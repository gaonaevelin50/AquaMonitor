param([string]$Cli = "C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe")
$ErrorActionPreference = "Stop"
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$source = Join-Path $workspace "esp32\aquamonitor_esp32"
$scratch = Join-Path $workspace ".test-runtime\firmware\aquamonitor_esp32"
$build = Join-Path $workspace ".test-runtime\firmware-build"
New-Item -ItemType Directory -Path $scratch -Force | Out-Null
foreach ($name in @("aquamonitor_esp32.ino", "secure_network.h", "water_level.h", "temperature_quality.h")) {
    Copy-Item -LiteralPath (Join-Path $source $name) -Destination (Join-Path $scratch $name) -Force
}
# Deliberately compile with the empty PUBLIC template, never private secrets.h.
Copy-Item -LiteralPath (Join-Path $source "secrets.h.example") -Destination (Join-Path $scratch "secrets.h") -Force
& $Cli compile --jobs 2 --fqbn "esp32:esp32:esp32:PartitionScheme=huge_app" --build-path $build $scratch
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación. No se cargó firmware." }

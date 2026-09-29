$ErrorActionPreference = "Stop"

$appDataRoot = Join-Path $env:LOCALAPPDATA "APPv2"
$llamaRoot = Join-Path $appDataRoot "llama.cpp"
$server = Get-ChildItem -Path $llamaRoot -Filter "llama-server.exe" -File -Recurse -ErrorAction SilentlyContinue |
    Select-Object -First 1
$model = Join-Path $appDataRoot "models\Qwen3.5-2B-Q4_K_M.gguf"
$logicalCpu = [Environment]::ProcessorCount
$safeThreads = [Math]::Max(1, [Math]::Min(4, [Math]::Floor($logicalCpu / 2)))

$env:APP_AI_BINARY = if ($server) { $server.FullName } else { Join-Path $llamaRoot "llama-server.exe" }
$env:APP_AI_MODEL = $model
$env:APP_AI_PORT = "8080"
$env:APP_AI_CONTEXT = "2048"
$env:APP_AI_THREADS = "$safeThreads"
$env:APP_AI_TIMEOUT = "120"
$env:APP_AI_EXECUTION_ENABLED = "0"
$env:APP_AI_SCHEMA_FORMAT = "nested"

Write-Host "APP v2 AI environment loaded (hardware execution disabled)."
Write-Host "llama-server: $env:APP_AI_BINARY"
Write-Host "model:        $env:APP_AI_MODEL"
Write-Host "CPU threads:  $env:APP_AI_THREADS of $logicalCpu logical processors"

if (-not (Test-Path -LiteralPath $env:APP_AI_BINARY)) {
    Write-Warning "Brak llama-server.exe. Uruchom: .\scripts\setup_llama_windows.ps1"
}
if (-not (Test-Path -LiteralPath $env:APP_AI_MODEL)) {
    Write-Warning "Brak modelu GGUF. Pobranie jest opcjonalne: .\scripts\setup_llama_windows.ps1 -DownloadModel"
}

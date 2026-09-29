param(
    [switch]$DownloadModel
)

$ErrorActionPreference = "Stop"
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "Ten skrypt obsługuje 64-bitowy Windows."
}

$appDataRoot = Join-Path $env:LOCALAPPDATA "APPv2"
$llamaRoot = Join-Path $appDataRoot "llama.cpp"
$modelsRoot = Join-Path $appDataRoot "models"
New-Item -ItemType Directory -Force -Path $llamaRoot, $modelsRoot | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $llamaRoot "llama-server.exe"))) {
    Write-Host "Pobieranie oficjalnego wydania ggml-org/llama.cpp dla Windows x64 CPU..."
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
    $asset = $release.assets | Where-Object { $_.name -match '^llama-.*-bin-win-cpu-x64\.zip$' } | Select-Object -First 1
    if (-not $asset) { throw "W najnowszym wydaniu nie znaleziono archiwum Windows x64 CPU." }
    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("appv2-llama-" + [guid]::NewGuid())
    $archive = "$tempRoot.zip"
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    try {
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath $tempRoot
        $server = Get-ChildItem -Path $tempRoot -Filter "llama-server.exe" -File -Recurse | Select-Object -First 1
        if (-not $server) { throw "Archiwum nie zawiera llama-server.exe." }
        Copy-Item -Path (Join-Path $server.Directory.FullName "*") -Destination $llamaRoot -Recurse -Force
    }
    finally {
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$modelPath = Join-Path $modelsRoot "Qwen3.5-2B-Q4_K_M.gguf"
if ($DownloadModel -and -not (Test-Path -LiteralPath $modelPath)) {
    Write-Host "Pobieranie dużego pliku modelu Qwen3.5-2B Q4_K_M..."
    $modelUrl = "https://huggingface.co/openresearchtools/Qwen3.5-2B-GGUF/resolve/main/Qwen3.5-2B-Q4_K_M.gguf?download=true"
    Invoke-WebRequest -Uri $modelUrl -OutFile $modelPath
}

Write-Host "llama-server: $(Join-Path $llamaRoot 'llama-server.exe')"
if (Test-Path -LiteralPath $modelPath) {
    Write-Host "model:        $modelPath"
} else {
    Write-Warning "Model nie został pobrany. Świadomie uruchom ponownie z parametrem -DownloadModel."
}

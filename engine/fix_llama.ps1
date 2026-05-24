$ErrorActionPreference = "Stop"
$WorkingDir = "d:\GITHUB\AGENT33\engine"
$Url = "https://github.com/ggml-org/llama.cpp/releases/download/b8116/llama-b8116-bin-win-cuda-12.4-x64.zip"
$OutPath = "$WorkingDir\bin\llama.zip"
$BinDir = "$WorkingDir\bin\llama-cpp"

if (Test-Path $BinDir) {
    Remove-Item -Recurse -Force $BinDir
}
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

Write-Host "Downloading llama.cpp CUDA archive b8116..."
Invoke-WebRequest -Uri $Url -OutFile $OutPath

Write-Host "Extracting..."
Expand-Archive -Path $OutPath -DestinationPath $BinDir -Force
Remove-Item $OutPath -ErrorAction SilentlyContinue
Write-Host "Extraction complete. llama-server.exe is ready."

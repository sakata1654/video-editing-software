# Build a standalone Windows executable: dist\IslamicVideoStudio.exe
# Usage: .\build_exe.ps1 [-IncludeFFmpeg]
param(
    [switch]$IncludeFFmpeg
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "1/4 Building React frontend..." -ForegroundColor Cyan
Set-Location "$Root\frontend"
npm ci
npm run build
Set-Location $Root

if ($IncludeFFmpeg) {
    Write-Host "2/4 Locating local ffmpeg/ffprobe to bundle..." -ForegroundColor Cyan
    $BundleDir = "$Root\ffmpeg_bundle"
    New-Item -ItemType Directory -Force -Path $BundleDir | Out-Null
    $ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
    $ffprobe = (Get-Command ffprobe -ErrorAction SilentlyContinue).Source
    if ($ffmpeg) { Copy-Item $ffmpeg "$BundleDir\ffmpeg.exe" -Force }
    if ($ffprobe) { Copy-Item $ffprobe "$BundleDir\ffprobe.exe" -Force }
} else {
    Write-Host "2/4 Skipping FFmpeg binary bundling (will use system PATH or .\ffmpeg\)" -ForegroundColor Yellow
}

Write-Host "3/4 Installing PyInstaller & backend dependencies..." -ForegroundColor Cyan
python -m pip install -r "$Root\backend\requirements.txt" pyinstaller

Write-Host "4/4 Packaging IslamicVideoStudio.exe..." -ForegroundColor Cyan
python -m PyInstaller --clean --noconfirm "$Root\islamic_video_studio.spec"

Write-Host "`nDone! Executable created at: $Root\dist\IslamicVideoStudio.exe" -ForegroundColor Green

# Build FaceIQ.exe from source: frontend -> static, bundle into the backend,
# then PyInstaller. Run windows\install-faceiq.ps1 afterwards to (re)install.
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')

Write-Host "[1/3] Building frontend..."
Push-Location (Join-Path $root 'frontend')
npm run build
Pop-Location

Write-Host "[2/3] Bundling UI into backend\web..."
$web = Join-Path $root 'backend\web'
if (Test-Path $web) { Remove-Item $web -Recurse -Force }
Copy-Item (Join-Path $root 'frontend\dist') $web -Recurse

Write-Host "[3/3] Packaging FaceIQ.exe with PyInstaller..."
Push-Location (Join-Path $root 'backend')
.\.venv\Scripts\pyinstaller.exe --noconfirm --windowed --name FaceIQ `
  --add-data "models;models" --add-data "web;web" --collect-submodules uvicorn `
  --hidden-import app.main --hidden-import app.vision --hidden-import app.db --hidden-import app.paths `
  --hidden-import multipart --hidden-import python_multipart faceiq_app.py
Pop-Location

Write-Host "Done -> backend\dist\FaceIQ\FaceIQ.exe"
Write-Host "Install + autostart: windows\install-faceiq.ps1"

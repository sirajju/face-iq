# Remove FaceIQ autostart + installed app (per-user). Your data in
# %LOCALAPPDATA%\FaceIQ is left intact; delete that folder too if you want.
$ErrorActionPreference = 'SilentlyContinue'

Get-Process FaceIQ | Stop-Process -Force

$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'FaceIQ.lnk'
if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "Removed autostart shortcut." }

$dst = Join-Path $env:LOCALAPPDATA 'Programs\FaceIQ'
if (Test-Path $dst) { Remove-Item $dst -Recurse -Force; Write-Host "Removed $dst." }

Write-Host "Done. Data kept at $env:LOCALAPPDATA\FaceIQ (delete manually to remove it)."

# Install FaceIQ as a Windows app that autostarts at logon.
# Copies the built app to a stable per-user location and adds a Startup shortcut.
# Run from a normal (non-admin) PowerShell: it's per-user, no elevation needed.
$ErrorActionPreference = 'Stop'

$src = Join-Path $PSScriptRoot '..\backend\dist\FaceIQ'
if (-not (Test-Path (Join-Path $src 'FaceIQ.exe'))) {
    throw "Build not found at $src. Build it first (see windows/PACKAGING.md)."
}

$dst = Join-Path $env:LOCALAPPDATA 'Programs\FaceIQ'
Write-Host "Installing to $dst ..."
# Stop a running instance so files can be replaced.
Get-Process FaceIQ -ErrorAction SilentlyContinue | Stop-Process -Force
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item (Join-Path $src '*') $dst -Recurse -Force

# Startup shortcut -> runs FaceIQ.exe at every logon.
$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup 'FaceIQ.lnk'
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = (Join-Path $dst 'FaceIQ.exe')
$sc.WorkingDirectory = $dst
$sc.Description = 'FaceIQ'
$sc.Save()

Write-Host "Installed. Autostart shortcut: $lnk"
Write-Host "Launching now..."
Start-Process (Join-Path $dst 'FaceIQ.exe')

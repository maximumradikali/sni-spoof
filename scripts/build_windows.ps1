param(
    [string]$Python = "python",
    [string]$Name = "sni-forwarder"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Write-Host "Installing build dependencies..."
& $Python -m pip install -r requirements-build.txt

Write-Host "Building Windows executable..."
& $Python -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --name $Name `
    --add-data "config.json;." `
    main.py

Write-Host "Build finished: dist\$Name.exe"

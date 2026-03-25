param(
    [string]$PythonCommand = "python",
    [string]$ExeName = "trae-patch",
    [string]$BundleName = "trae-patch-windows-x64"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$distDir = Join-Path $repoRoot "dist"
$buildDir = Join-Path $repoRoot "build"
$workDir = Join-Path $repoRoot ".pyinstaller"
$bundleDir = Join-Path $distDir $BundleName
$entryScript = Join-Path $repoRoot "src\trae_custom_endpoint_patch\__main__.py"
$exePath = Join-Path $distDir ($ExeName + ".exe")
$zipPath = Join-Path $distDir ($BundleName + ".zip")

Set-Location $repoRoot

Remove-Item $buildDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $workDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $bundleDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

Write-Host "Installing build dependencies..."
& $PythonCommand -m pip install --upgrade pip
& $PythonCommand -m pip install . pyinstaller

Write-Host "Building $ExeName.exe ..."
& $PythonCommand -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --name $ExeName `
    --distpath $distDir `
    --workpath $workDir `
    --specpath $buildDir `
    --paths (Join-Path $repoRoot "src") `
    $entryScript

if (-not (Test-Path $exePath)) {
    throw "Expected executable was not created: $exePath"
}

New-Item -ItemType Directory -Path $bundleDir | Out-Null
Copy-Item $exePath -Destination $bundleDir
Copy-Item (Join-Path $repoRoot "README.md") -Destination $bundleDir
Copy-Item (Join-Path $repoRoot "examples") -Destination (Join-Path $bundleDir "examples") -Recurse

Compress-Archive -Path $bundleDir -DestinationPath $zipPath -Force

Write-Host "Build completed."
Write-Host "Executable: $exePath"
Write-Host "Bundle zip: $zipPath"

<#
.SYNOPSIS
    Build 3DXWorldEditor.exe: one standalone file with the editor, the local server and the asset extractor.
.DESCRIPTION
    - creates .venv and installs build requirements
    - runs PyInstaller (single file, console window so you can see the address and stop it with Ctrl+C)
    - runs the exe's self-test
    - writes dist\SHA256SUMS.txt (the 3DXModKit installer verifies against it)
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File build\build.ps1
#>
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = (Get-Content VERSION -TotalCount 1).Trim()
$appName = "3DX World Editor"
Write-Host "Building $appName $version" -ForegroundColor Cyan

# --- Python environment ------------------------------------------------------
if (-not (Test-Path .venv\Scripts\python.exe)) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { & py -3 -m venv .venv } else { & python -m venv .venv }
}
$python = Join-Path $root ".venv\Scripts\python.exe"
& $python -m pip install --quiet --disable-pip-version-check -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# --- Icon & version resource ---------------------------------------------------
& $python build\make_icon.py build
$v = ($version.Split(".") + @("0", "0", "0", "0"))[0..3] -join ", "
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($v), prodvers=($v), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', '$appName'),
    StringStruct('ProductName', '$appName'),
    StringStruct('FileVersion', '$version'),
    StringStruct('ProductVersion', '$version'),
    StringStruct('OriginalFilename', '3DXWorldEditor.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -Encoding utf8 build\version_info.txt

# --- PyInstaller ---------------------------------------------------------------
New-Item -ItemType Directory -Force dist | Out-Null
Get-ChildItem dist -File -ErrorAction SilentlyContinue | Remove-Item -Force
& $python -m compileall -q server.py extract_assets.py gamepath.py
if ($LASTEXITCODE -ne 0) { throw "source does not compile" }

& $python -m PyInstaller --noconfirm --clean --onefile --console --name 3DXWorldEditor `
    --icon "$root\build\icon.ico" --version-file "$root\build\version_info.txt" `
    --add-data "$root\docs;docs" --collect-all UnityPy --collect-data archspec --hidden-import extract_assets `
    --exclude-module matplotlib --exclude-module tkinter --exclude-module fmod_toolkit `
    --distpath "$root\dist" --workpath "$root\build\work" --specpath "$root\build\work" server.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path $root "dist\3DXWorldEditor.exe"
$report = Join-Path $root "build\selftest.txt"
$p = Start-Process -FilePath $exe -ArgumentList "--selftest", "`"$report`"" -Wait -PassThru -WindowStyle Hidden
Get-Content $report -ErrorAction SilentlyContinue
if ($p.ExitCode -ne 0) { throw "self-test failed" }
Write-Host "Self-test passed" -ForegroundColor Green

# --- Checksums -----------------------------------------------------------------
$sums = Get-ChildItem dist -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
}
$sums | Set-Content -Encoding ascii dist\SHA256SUMS.txt
Write-Host "Built dist\3DXWorldEditor.exe ($([math]::Round((Get-Item $exe).Length / 1MB, 1)) MB)" -ForegroundColor Green

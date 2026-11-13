# Freeze the Python processing engine into engine\dist\docsuite-engine\ (a folder with
# docsuite-engine.exe and its libraries). The desktop app ships that folder, so end users
# do not need Python.
#
#   powershell -ExecutionPolicy Bypass -File scripts\build_engine.ps1
#
# Must be run on the operating system you are building for.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'engine\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "engine\.venv is missing - run 'npm run engine:setup' first." }

& $python -m PyInstaller --noconfirm --clean --onedir --console --name docsuite-engine `
    --distpath (Join-Path $root 'engine\dist') `
    --workpath (Join-Path $root 'engine\build') `
    --specpath (Join-Path $root 'engine\build') `
    --paths (Join-Path $root 'engine') `
    --collect-data docx --collect-data pptx --collect-data reportlab `
    --collect-all pypdfium2 --collect-all pypdfium2_raw `
    --collect-data pyhanko --collect-data pyhanko_certvalidator --collect-data tzdata `
    --exclude-module tkinter --exclude-module pytest --exclude-module PyInstaller `
    (Join-Path $root 'engine\run_engine.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$exe = Join-Path $root 'engine\dist\docsuite-engine\docsuite-engine.exe'
$size = (Get-ChildItem (Split-Path $exe) -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
"Built $exe ({0:N0} MB)" -f $size

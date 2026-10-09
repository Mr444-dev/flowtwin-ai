$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw 'Python was not found. Install Python 3.10 or later, then run this script again.'
}

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
}
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$flowtwin = Join-Path $PSScriptRoot '.venv\Scripts\flowtwin.exe'
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Could not upgrade pip.' }
& $venvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw 'Could not install project dependencies.' }

if (-not (Test-Path 'data\raw\BPI Challenge 2017.xes.gz')) {
    & $flowtwin download
    if ($LASTEXITCODE -ne 0) { throw 'Could not download the event log.' }
}
if (-not (Test-Path 'data\processed\flowtwin.sqlite3')) {
    & $flowtwin prepare
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the data.' }
}
if (-not (Test-Path 'artifacts\remaining_time.joblib')) {
    & $flowtwin train
    if ($LASTEXITCODE -ne 0) { throw 'Model training failed.' }
}

Write-Host 'Opening FlowTwin AI at http://127.0.0.1:8000'
Start-Sleep -Seconds 2
Start-Process 'http://127.0.0.1:8000'
& $flowtwin serve

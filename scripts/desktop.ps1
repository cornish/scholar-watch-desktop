$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venv = Join-Path $root ".venv\Scripts\Activate.ps1"

if (-not (Test-Path $venv)) {
    Write-Host "Creating virtual environment..."
    python -m venv (Join-Path $root ".venv")
    & $venv
    pip install -e $root | Out-Null
} else {
    & $venv
}

scholar-watch init-db
scholar-watch desktop

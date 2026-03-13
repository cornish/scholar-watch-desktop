# Initialize the Scholar Watch database
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

# Activate virtual environment
if (Test-Path "$ProjectDir\venv\Scripts\Activate.ps1") {
    & "$ProjectDir\venv\Scripts\Activate.ps1"
} elseif (Test-Path "$ProjectDir\.venv\Scripts\Activate.ps1") {
    & "$ProjectDir\.venv\Scripts\Activate.ps1"
}

python -m scholar_watch.cli init-db @args

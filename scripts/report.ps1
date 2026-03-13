# Generate and send Scholar Watch email report
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

if (Test-Path "$ProjectDir\venv\Scripts\Activate.ps1") {
    & "$ProjectDir\venv\Scripts\Activate.ps1"
} elseif (Test-Path "$ProjectDir\.venv\Scripts\Activate.ps1") {
    & "$ProjectDir\.venv\Scripts\Activate.ps1"
}

python -m scholar_watch.cli report @args

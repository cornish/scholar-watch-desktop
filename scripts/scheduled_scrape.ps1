# Scheduled Scholar Watch scrape
# Run via Windows Task Scheduler (e.g., twice per week).
#
# Task Scheduler setup:
#   1. Create Basic Task -> Weekly, pick days (e.g., Monday + Thursday)
#   2. Action: Start a program
#      Program: powershell.exe
#      Arguments: -ExecutionPolicy Bypass -File "D:\Github\scholar_watch\scripts\scheduled_scrape.ps1"
#      Start in: D:\Github\scholar_watch

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

# Use the venv Python directly — no activation needed
$Python = Join-Path $ProjectDir "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
}

if (-not (Test-Path $Python)) {
    Write-Error "Python not found in venv"
    exit 1
}

& $Python -m scholar_watch.cli scrape

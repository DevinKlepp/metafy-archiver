# One-time setup for Windows (run in PowerShell from this folder):  .\setup.ps1
# Creates a private Python environment in .venv, installs the dependencies and the browser.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = $null
foreach ($c in @("py -3.13", "py -3.12", "py -3.11", "py -3.10", "py -3", "python")) {
  try {
    $v = & cmd /c "$c -c `"import sys; print(sys.version_info >= (3, 10))`"" 2>$null
    if ($v -eq "True") { $py = $c; break }
  } catch {}
}
if (-not $py) {
  Write-Host "Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run this again."
  exit 1
}

Write-Host "Using: $py"
if (-not (Test-Path ".venv")) { & cmd /c "$py -m venv .venv" }
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
& .\.venv\Scripts\python.exe -m playwright install chromium

Write-Host ""
Write-Host "Setup complete. To archive a guide:"
Write-Host ""
Write-Host '  .\archive "https://metafy.gg/guides/view/<guide>"'
Write-Host ""
Write-Host "A browser window opens; log in to Metafy the first time, then press Enter in this window."
Write-Host "To archive everything you have bought, run .\archive with no arguments."

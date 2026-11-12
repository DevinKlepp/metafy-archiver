@echo off
rem One-time setup for Windows. Run .\setup.cmd in PowerShell (or double-click it).
rem It runs setup.ps1 with the script policy relaxed for this one run only, which is needed when
rem the project was downloaded as a ZIP: Windows marks the extracted files as from the internet
rem and the default policy then refuses to run .ps1 files ("not digitally signed").
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set code=%ERRORLEVEL%
if not "%code%"=="0" (
  echo Setup did not finish ^(exit code %code%^). Scroll up for the error.
  pause
)
exit /b %code%

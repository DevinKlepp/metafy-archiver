@echo off
rem Runs the archiver with the environment created by setup.ps1. Usage: archive [guide URL ...] [options]
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Run .\setup.cmd first ^(it creates the .venv folder this script needs^).
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0metafy_archiver.py" %*

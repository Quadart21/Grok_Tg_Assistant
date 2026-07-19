@echo off
setlocal
cd /d "%~dp0"

echo Installing Python 3.11 via winget...
echo.

where winget >nul 2>&1
if errorlevel 1 (
  echo winget not found. Use Microsoft Store or download manually:
  echo https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
  pause
  exit /b 1
)

winget install --id Python.Python.3.11 -e --accept-package-agreements --accept-source-agreements

echo.
echo Done. Close this window and run start.bat
echo.
py -3.11 --version
pause

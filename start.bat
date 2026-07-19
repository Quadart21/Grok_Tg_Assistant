@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PY_CMD="
set "PY_LABEL="
set "TDATA_OK=1"

for %%V in (3.11 3.12 3.10) do (
  if not defined PY_CMD (
    py -%%V -c "import sys" >nul 2>&1
    if not errorlevel 1 (
      set "PY_CMD=py -%%V"
      set "PY_LABEL=%%V"
    )
  )
)

if not defined PY_CMD (
  echo Python 3.10-3.12 not found. Trying winget install Python 3.11...
  where winget >nul 2>&1
  if not errorlevel 1 (
    winget install --id Python.Python.3.11 -e --accept-package-agreements --accept-source-agreements
    py -3.11 -c "import sys" >nul 2>&1
    if not errorlevel 1 (
      set "PY_CMD=py -3.11"
      set "PY_LABEL=3.11"
    )
  )
)

if not defined PY_CMD (
  for %%V in (3.13 3.14 3.15) do (
    if not defined PY_CMD (
      py -%%V -c "import sys" >nul 2>&1
      if not errorlevel 1 (
        set "PY_CMD=py -%%V"
        set "PY_LABEL=%%V"
        set "TDATA_OK=0"
      )
    )
  )
)

if not defined PY_CMD (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "PY_CMD=py -3"
    for /f "delims=" %%i in ('py -3 -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"') do set "PY_LABEL=%%i"
    if not "!PY_LABEL!"=="3.11" if not "!PY_LABEL!"=="3.12" if not "!PY_LABEL!"=="3.10" set "TDATA_OK=0"
  )
)

if not defined PY_CMD (
  python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "PY_CMD=python"
    for /f "delims=" %%i in ('python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"') do set "PY_LABEL=%%i"
    if not "!PY_LABEL!"=="3.11" if not "!PY_LABEL!"=="3.12" if not "!PY_LABEL!"=="3.10" set "TDATA_OK=0"
  )
)

if not defined PY_CMD (
  echo.
  echo  ERROR: Python 3.10+ not found.
  echo.
  echo  Run install_python.bat  OR  in cmd:
  echo    winget install Python.Python.3.11
  echo.
  echo  Direct installer:
  echo  https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
  echo.
  pause
  exit /b 1
)

if "!TDATA_OK!"=="0" (
  echo.
  echo  NOTE: Python !PY_LABEL! — panel OK, tdata converter disabled.
  echo  For tdata: winget install Python.Python.3.11
  echo.
)

set "RECREATE=0"
if not exist "venv\Scripts\python.exe" set "RECREATE=1"
if "!RECREATE!"=="0" (
  for /f "delims=" %%i in ('venv\Scripts\python.exe -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"') do set "VENV_VER=%%i"
  if not "!VENV_VER!"=="!PY_LABEL!" set "RECREATE=1"
)

if "!RECREATE!"=="1" (
  echo Creating venv: !PY_CMD!
  if exist "venv" rmdir /s /q "venv"
  !PY_CMD! -m venv venv
  if errorlevel 1 (
    echo ERROR: failed to create venv
    pause
    exit /b 1
  )
)

call venv\Scripts\activate.bat
if errorlevel 1 (
  echo ERROR: cannot activate venv
  pause
  exit /b 1
)

set PYTHONUTF8=1
python -m pip install --upgrade pip wheel
if errorlevel 1 goto :pip_fail

echo Installing core dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto :pip_fail

if "!TDATA_OK!"=="1" (
  echo Installing tdata converter ^(opentele^)...
  python -m pip install -r requirements-tdata.txt
  if errorlevel 1 (
    echo WARNING: opentele not installed — tdata conversion unavailable.
  )
) else (
  echo Skipping opentele ^(needs Python 3.10-3.12^).
)

echo.
echo  Kot_Teamlead - Telegram panel
python -c "import sys; print('  Python', sys.version.split()[0])"
echo  http://127.0.0.1:8787/
echo.

python main.py
pause
exit /b 0

:pip_fail
echo ERROR: requirements install failed
pause
exit /b 1

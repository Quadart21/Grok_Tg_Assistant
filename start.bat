@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: python -m venv failed. Install Python 3.10+ and add it to PATH.
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
if errorlevel 1 (
    echo ERROR: pip upgrade failed
    pause
    exit /b 1
)

python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: requirements install failed
    pause
    exit /b 1
)

echo.
echo  Kot_Teamlead - Telegram panel
echo  Developer: Kot_Teamlead
echo.
echo  Browser: http://127.0.0.1:8787/
echo  Local PC only
echo.

python main.py
pause

@echo off
TITLE Deep Focus Installer
CLS

ECHO    ___                  _____                   
ECHO   / _ \___ ___ ___     / __/___________ __ ___ 
ECHO  / // / -_) -_) _ \   / _// _ \/ __/ // (_-^< 
ECHO /____/\__/\__/ .__/  /_/  \___/\__/\_,_/___/ 
ECHO             /_/                              
ECHO.
ECHO [*] Deep Focus Installer initializing...
ECHO.

:: 1. Check Python
python --version >NUL 2>&1
IF %ERRORLEVEL% NEQ 0 (
    ECHO [!] Python not found. Please install Python 3.8+ and add it to PATH.
    PAUSE
    EXIT /B 1
)

:: 2. Setup Virtual Environment
IF EXIST "venv" (
    ECHO [*] Virtual environment already exists.
) ELSE (
    ECHO [*] Creating virtual environment ^(venv^)...
    python -m venv venv
)

:: 3. Install Dependencies
ECHO [*] Installing dependencies...
call venv\Scripts\activate.bat
pip install rich aiosqlite --upgrade

:: 4. Create Launcher
ECHO [*] Creating launcher...
(
ECHO @echo off
ECHO cd /d "%CD%"
ECHO call venv\Scripts\activate.bat
ECHO python deep_focus.py %%*
) > deepfocus.bat

:: 5. Add to PATH (PowerShell)
ECHO [*] Adding installation directory to User PATH...
powershell -Command "[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path', 'User') + ';%CD%', 'User')"

ECHO.
ECHO [+] Installation Complete!
ECHO [+] You can now open a NEW terminal and type: deepfocus
ECHO.
PAUSE

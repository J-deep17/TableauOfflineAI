@echo off
setlocal
cd /d "%~dp0"
title Building Tableau Offline AI
set PY=
for %%V in (3.12 3.13 3.11 3.14) do (
  if not defined PY ( py -%%V -c "import tkinter" >nul 2>nul && set PY=py -%%V )
)
if not defined PY ( where py >nul 2>nul && set PY=py -3 )
if not defined PY ( where python >nul 2>nul && set PY=python )
if not defined PY (
  echo Python was not found. Install Python 3.12 from https://www.python.org/downloads/
  echo IMPORTANT: tick "Add python.exe to PATH" and keep "tcl/tk and IDLE" ticked.
  pause & exit /b 1
)
echo Using: %PY%
%PY% --version
echo [1/3] Installing build tools (needs internet, one time)...
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install --upgrade pandas numpy openpyxl xlrd pyinstaller pyinstaller-hooks-contrib || ( echo Install failed. & pause & exit /b 1 )
echo [2/3] Building the app (2-5 minutes)...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name TableauOfflineAI ^
  --collect-submodules openpyxl --hidden-import xlrd ^
  --exclude-module matplotlib --exclude-module scipy --exclude-module IPython ^
  TableauOfflineAI.py || goto :fail
echo [3/3] Done.
echo.
echo Your app:  %~dp0dist\TableauOfflineAI.exe
echo Copy that single file anywhere. No Python needed to run it.
explorer "%~dp0dist"
pause & exit /b 0
:fail
echo.
echo Build failed. If your Python is very new (3.15), install Python 3.12 from
echo https://www.python.org/downloads/release/python-3120/  then run this file again.
pause & exit /b 1

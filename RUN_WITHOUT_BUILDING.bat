@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m pip install -q pandas numpy openpyxl xlrd & py -3 TableauOfflineAI.py & exit /b)
python -m pip install -q pandas numpy openpyxl xlrd & python TableauOfflineAI.py

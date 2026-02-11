@echo off
echo.
echo ========================================
echo  Chart Trend Analyzer - Starting...
echo ========================================
echo.

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Start the server
python chart_analyzer_server.py

pause

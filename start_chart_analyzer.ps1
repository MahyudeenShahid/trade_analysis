# Chart Analyzer Launcher
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Chart Trend Analyzer - Starting..." -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Activate virtual environment
& ".\.venv\Scripts\Activate.ps1"

# Start the server
python chart_analyzer_server.py

Read-Host "Press Enter to exit"

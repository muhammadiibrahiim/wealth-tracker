# Start script for Wealth Tracker application (PowerShell)

Write-Host "Starting Wealth Tracker on port 8003..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Activate virtual environment if it exists
if (Test-Path "venv") {
    Write-Host "Activating virtual environment..." -ForegroundColor Cyan
    .\venv\Scripts\Activate.ps1
} elseif (Test-Path ".venv") {
    Write-Host "Activating virtual environment..." -ForegroundColor Cyan
    .\.venv\Scripts\Activate.ps1
}

# Start the FastAPI application
python -m uvicorn main:app --reload --port 8003

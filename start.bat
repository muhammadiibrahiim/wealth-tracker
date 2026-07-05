@echo off
REM Start script for Wealth Tracker application (Windows Batch)

echo Starting Wealth Tracker on port 8003...
echo Press Ctrl+C to stop the server
echo.

REM Activate virtual environment if it exists
if exist "venv\" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else if exist ".venv\" (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
)

REM Start the FastAPI application
python -m uvicorn main:app --reload --port 8003

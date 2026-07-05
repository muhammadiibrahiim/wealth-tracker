#!/bin/bash
# Start script for Wealth Tracker application

echo "Starting Wealth Tracker on port 8003..."
echo "Press Ctrl+C to stop the server"
echo ""

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
elif [ -d ".venv" ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
fi

# Start the FastAPI application
python -m uvicorn main:app --reload --port 8003

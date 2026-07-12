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

# Snapshot the DB, then apply any pending schema migrations before serving.
if [ -f "wealth_tracker.db" ]; then
    cp -p wealth_tracker.db "wealth_tracker.db.backup-$(date +%F)" 2>/dev/null || true
fi
python -m alembic upgrade head || echo "WARN: alembic migration failed"

# Start the FastAPI application
python -m uvicorn main:app --reload --port 8003

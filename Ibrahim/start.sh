#!/usr/bin/env bash
# Self-bootstrapping launcher for Ibrahim Traders (Mac / Linux).
# First run installs everything; subsequent runs just start the server.

set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "  Ibrahim Traders - launcher"
echo "============================================================"
echo

# ----- 1. Find a Python interpreter ---------------------------
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "[X] Python is not installed on this computer."
    echo
    echo "    Install Python 3.10 or newer:"
    echo "      Mac:   https://www.python.org/downloads/   (or  brew install python)"
    echo "      Linux: sudo apt install python3 python3-venv python3-pip"
    echo
    echo "    Then run this start.sh again."
    read -rp "Press Enter to exit..."
    exit 1
fi

echo "[OK] $($PY --version) found."

# ----- 2. Virtual environment ---------------------------------
if [ ! -x "venv/bin/python" ]; then
    echo
    echo "First-time setup: creating a virtual environment in ./venv ..."
    $PY -m venv venv
    echo "[OK] venv created."
fi

# shellcheck disable=SC1091
source venv/bin/activate

# ----- 3. Required Python packages ----------------------------
if ! python -c "import uvicorn, fastapi, sqlmodel, jinja2, alembic, multipart" >/dev/null 2>&1; then
    echo
    echo "First-time setup: installing required packages..."
    echo "This takes a minute or two on the first run."
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    echo "[OK] Packages installed."
else
    echo "[OK] Packages already installed."
fi

# ----- 4. Launch ----------------------------------------------
echo
echo "============================================================"
echo "  Starting Ibrahim Traders on http://localhost:8003"
echo "  Press Ctrl+C in this window to stop the server."
echo "============================================================"
echo

# Open the browser shortly after the server boots (Mac / Linux best-effort).
(
    sleep 3
    if command -v open >/dev/null 2>&1; then
        open http://localhost:8003 || true
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open http://localhost:8003 || true
    fi
) &

python -m uvicorn main:app --port 8003

echo
echo "Server stopped."
read -rp "Press Enter to close this window..."

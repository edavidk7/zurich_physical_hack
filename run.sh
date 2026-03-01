#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# Install frontend deps if needed
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "node_modules not found, running npm install..."
    (cd "$FRONTEND_DIR" && npm install)
fi

# Kill both processes on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
    echo "Done."
}
trap cleanup EXIT INT TERM

echo "Starting backend (port 8000)..."
cd "$SCRIPT_DIR"
uv run python server.py &
BACKEND_PID=$!

echo "Starting frontend (port 3000)..."
(cd "$FRONTEND_DIR" && npm run dev) &
FRONTEND_PID=$!

echo ""
echo "Backend:  http://localhost:8000"
echo "Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both."

wait

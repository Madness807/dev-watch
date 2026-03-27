#!/bin/bash
cd "$(dirname "$0")"

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
  echo "Dependencies installed."
fi

# Kill previous server if running
pkill -f "python3.*src/server.py" 2>/dev/null
pkill -f "python3.*src.server" 2>/dev/null

# Start server using venv Python
.venv/bin/python3 -m src.server &
SERVER_PID=$!

# Wait for server to be ready
for i in {1..10}; do
  curl -s http://localhost:3999/api/health > /dev/null 2>&1 && break
  sleep 0.3
done

# Open dashboard in browser
xdg-open "http://localhost:3999" 2>/dev/null

echo "dev-watch started (PID: $SERVER_PID)"
echo "Ctrl+C to stop"
wait $SERVER_PID

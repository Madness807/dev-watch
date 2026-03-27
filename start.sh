#!/bin/bash
cd "$(dirname "$0")"

# Kill previous server if running
pkill -f "python3 $(pwd)/server.py" 2>/dev/null

# Start server in background
python3 server.py &
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

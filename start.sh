#!/bin/bash
cd "$(dirname "$0")"

# Kill l'ancien serveur si il tourne
pkill -f "python3.*server.py" 2>/dev/null

# Lance le serveur en arrière-plan
python3 server.py &
SERVER_PID=$!

# Attend que le serveur soit prêt
for i in {1..10}; do
  curl -s http://localhost:3999/api/health > /dev/null 2>&1 && break
  sleep 0.3
done

# Ouvre le dashboard
xdg-open "$(pwd)/dev-watch.html" 2>/dev/null

echo "dev-watch demarre (PID: $SERVER_PID)"
echo "Ctrl+C pour arreter"
wait $SERVER_PID

#!/bin/bash
set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

# ── Commands ──

install_service() {
  echo "Generating systemd service..."
  sed "s|__USER__|$(whoami)|g; s|__PATH__|${PROJECT_DIR}|g" \
    dev-watch.service > /tmp/dev-watch.service

  echo "Installing service (requires sudo)..."
  sudo cp /tmp/dev-watch.service /etc/systemd/system/dev-watch.service
  rm /tmp/dev-watch.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now dev-watch
  sudo systemctl status dev-watch --no-pager
  echo "dev-watch service installed and started."
  exit 0
}

uninstall_service() {
  echo "Removing service (requires sudo)..."
  sudo systemctl stop dev-watch 2>/dev/null
  sudo systemctl disable dev-watch 2>/dev/null
  sudo rm -f /etc/systemd/system/dev-watch.service
  sudo systemctl daemon-reload
  echo "dev-watch service removed."
  exit 0
}

show_help() {
  echo "Usage: ./start.sh [command]"
  echo ""
  echo "Commands:"
  echo "  (none)      Start dev-watch and open dashboard"
  echo "  install     Install as systemd service (auto-start on boot)"
  echo "  uninstall   Remove systemd service"
  echo "  help        Show this help"
  exit 0
}

# ── Parse command ──

case "${1:-}" in
  install)   install_service ;;
  uninstall) uninstall_service ;;
  help|-h)   show_help ;;
esac

# ── Default: start server ──

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
  echo "Dependencies installed."
fi

# Kill previous server if running
pkill -f "python3.*src/server.py" 2>/dev/null || true
pkill -f "python3.*src.server" 2>/dev/null || true

# Start server using venv Python
.venv/bin/python3 -m src.server &
SERVER_PID=$!

# Wait for server to be ready
for i in {1..10}; do
  curl -s http://localhost:3999/api/health > /dev/null 2>&1 && break
  sleep 0.3
done

# Open dashboard in browser (cross-platform: Linux, WSL2, macOS)
if grep -qi microsoft /proc/version 2>/dev/null; then
  # WSL2: prefer wslview (wslu package), fall back to powershell.exe
  if command -v wslview >/dev/null 2>&1; then
    wslview "http://localhost:3999" 2>/dev/null || true
  else
    powershell.exe Start-Process "http://localhost:3999" 2>/dev/null || true
  fi
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://localhost:3999" 2>/dev/null || true
elif command -v open >/dev/null 2>&1; then
  open "http://localhost:3999" 2>/dev/null || true
fi

echo "dev-watch started (PID: $SERVER_PID)"
echo "Ctrl+C to stop"
wait $SERVER_PID

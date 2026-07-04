#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

# ── Helpers ──

ensure_venv() {
  # Rebuild if missing/broken, then keep deps in sync (no-op when satisfied).
  if [ ! -x .venv/bin/python3 ]; then
    echo "Creating virtual environment..."
    rm -rf .venv
    python3 -m venv .venv
  fi
  .venv/bin/pip install -q -r requirements.txt
}

# ── Commands ──

install_service() {
  TARGET_USER="${SUDO_USER:-$(whoami)}"
  if [ "$TARGET_USER" = "root" ]; then
    echo "Refusing to install: dev-watch must not run as root." >&2
    echo "Run './start.sh install' as your normal user (it calls sudo itself)." >&2
    exit 1
  fi

  ensure_venv

  echo "Generating systemd service..."
  sed "s|__USER__|${TARGET_USER}|g; s|__PATH__|${PROJECT_DIR}|g" \
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
  sudo systemctl stop dev-watch 2>/dev/null || true
  sudo systemctl disable dev-watch 2>/dev/null || true
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

# Don't fight the systemd-managed instance (a manual SIGTERM looks like a clean
# exit to systemd, so Restart=on-failure would NOT bring it back).
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet dev-watch; then
  echo "dev-watch is running as a systemd service."
  echo "Stop it first with: sudo systemctl stop dev-watch"
  exit 1
fi

ensure_venv

# Stop a previous manual instance (anchored so we don't kill unrelated python procs)
pkill -f -- '-m src\.server' 2>/dev/null || true

# Start server using venv Python
.venv/bin/python3 -m src.server &
SERVER_PID=$!

# Wait for server to be ready
for i in {1..10}; do
  curl -s http://localhost:3999/api/health > /dev/null 2>&1 && break
  sleep 0.3
done

# Open dashboard in browser (best-effort; never abort the launcher)
command -v xdg-open >/dev/null 2>&1 && xdg-open "http://localhost:3999" >/dev/null 2>&1 || true

echo "dev-watch started (PID: $SERVER_PID)"
echo "Ctrl+C to stop"
wait $SERVER_PID

"""Shared configuration constants for dev-watch."""

import os

HOST = "127.0.0.1"
PORT = 3999

# Command used by POST /api/open to open a project directory. Override for your
# environment, e.g. DEV_WATCH_OPEN_CMD=code (VS Code), wslview or explorer.exe (WSL).
OPEN_CMD = os.environ.get("DEV_WATCH_OPEN_CMD", "xdg-open")

<p align="center">
  <img src="static/icons/dev-watch-logo.svg" alt="dev-watch logo" width="80" height="80">
</p>

<h1 align="center">DEV WATCH</h1>

<p align="center">
  <strong>v1.5.0</strong> — Local web dashboard to monitor and manage processes, Docker containers, network ports and connections on your dev machine.
</p>

<!-- Screenshot will be added in a future update -->

> [!CAUTION]
> **This tool is designed for LOCAL USE ONLY.**
> It must NEVER be exposed on a network, VPN, reverse proxy, or the Internet.
> There is no authentication. Anyone who can reach port 3999 can see your processes
> and kill them. Do not change the bind from `127.0.0.1` to `0.0.0.0`.

---

## Table of Contents

- [Tech Stack](#tech-stack)
- [Features](#features)
- [Installation](#installation)
- [Security](#security)
- [Architecture](#architecture)
- [API](#api)
- [Requirements](#requirements)
- [Platform Support](#platform-support)
- [Contributing](#contributing)
- [License](#license)

---

## Tech Stack

| Technology | Usage |
|-----------|-------|
| ![Python](https://img.shields.io/badge/Python_3-3776AB?logo=python&logoColor=white) | Backend server, process scanning, system metrics |
| ![Flask](https://img.shields.io/badge/Flask-000000?logo=flask&logoColor=white) | REST API + static file serving |
| ![HTML5](https://img.shields.io/badge/HTML5-E34F26?logo=html5&logoColor=white) | Single-file dashboard (no build step) |
| ![JavaScript](https://img.shields.io/badge/Vanilla_JS-F7DF1E?logo=javascript&logoColor=black) | Frontend logic, Web Audio API, Notification toasts |
| ![CSS3](https://img.shields.io/badge/CSS3-1572B6?logo=css3&logoColor=white) | Dark theme, responsive layout, animations |
| ![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white) | Container monitoring (optional) |
| ![SVG](https://img.shields.io/badge/SVG_Icons-FFB13B?logo=svg&logoColor=black) | 23 local tech icons from [Dashboard Icons](https://dashboardicons.com/) (zero CDN, served locally) |

## Features

### Processes
- Auto-detection of **Node.js**, **Python**, **Rust** (cargo), **Go** (go run), **Deno**, **Bun**, **Java** (java/mvn/gradle), **PHP** (php/composer), **Ruby** (ruby/rails/bundle), and **C/C++** (gcc/make/cmake/gdb) processes
- **Native binary detection**: compiled ELF binaries (C++, Go, Zig, etc.) running from `$HOME` are detected as `native` via `/proc/{pid}/exe` + ELF magic bytes
- Excludes system services and Docker container processes
- Venv detection: shows which Python virtual environment a process runs in
- **Per-process CPU & RAM**: instantaneous CPU% (sampled between scans, like `htop` — can exceed 100% on multi-core processes) and resident memory (MB). CPU shows `0%` on the very first scan, then real values once a baseline exists
- **Trend sparklines**: a tiny SVG trend line next to each CPU/MEM value (and next to the toolbar CPU/RAM/disk meters) over the last ~40 scans — spot a spike vs a steady load, or a slowly climbing memory leak. History is kept client-side and resets on reload
- Quick filter buttons by type (11 types)
- Sortable columns (type, PID, CPU, MEM, project)
- Kill button (SIGTERM)
- **Quick actions**: click a port to open `http://localhost:<port>` in your browser, copy its URL (`⧉`), copy the project path (click the directory), or open the project folder (`dir` button — see `DEV_WATCH_OPEN_CMD` below)

> [!NOTE]
> **Compiled binaries**: Interpreted languages (Node, Python, Ruby, etc.) are identified by their interpreter in the command line. Compiled binaries (`./my-app`) have no such marker, so they are detected as `native` if the executable is an ELF binary located in your home directory.
> Shell scripts (bash/zsh) are intentionally excluded to avoid noise from terminal sessions.

### Docker Containers
- Grouped by compose project with accordion
- Health indicator: green (healthy), orange (unhealthy), red (down)
- Auto tech detection from container name (23 icons)
- Image version tag: orange (latest), green (pinned version)
- Host-bound ports (host:container) vs internal-only ports
- Restart / stop buttons

### Network
- **Listening Ports (TCP)**: full machine scan, not just Node/Python — click a port to open it in the browser or copy its URL
- **Active Connections (TCP)**: all ESTABLISHED connections with process and PID
- Bind indicator: green (127.0.0.1) vs red (0.0.0.0)

### System
- Resource meters in toolbar: CPU, RAM, disk, GPU (nvidia)
- Color-coded by usage (green < 60%, yellow < 85%, red > 85%)

### Interface
- Section accordions (open/close on click)
- In-page toast notifications for events (process terminated, container unhealthy, etc.)
- Subtle sound notifications via Web Audio API (up/down tones)
- Configurable watch: 3s / 5s / 10s / off
- Status line: green blink (live) / red (watch off)
- Global text filter (PID, project, port, type, command)
- Disclaimer button with security rules
- Zero external network calls (local icons, no CDN, no Google Fonts)

## Installation

```bash
# Clone the repo
git clone https://github.com/Madness807/dev-watch.git
cd dev-watch

# Launch (auto-creates venv + installs dependencies on first run)
./start.sh
```

That's it. `start.sh` handles everything:
1. Creates (or repairs) a Python virtual environment (`.venv/`)
2. Installs runtime dependencies (`flask`) inside the venv, keeping them in sync on each start
3. Starts the server on `http://localhost:3999`
4. Opens the dashboard in your browser (best-effort; the launcher still runs on headless/WSL hosts without `xdg-open`)

Press `Ctrl+C` to stop.

### Running the tests

```bash
.venv/bin/pip install -r requirements-dev.txt   # adds pytest
.venv/bin/python3 -m pytest tests/ -q
```

### Systemd (optional, auto-start on boot)

```bash
# Automatically generates the service file with your user and paths
./start.sh install

# To remove
./start.sh uninstall
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEV_WATCH_OPEN_CMD` | `xdg-open` | Command used by the `dir` button (`POST /api/open`) to open a project folder. Set to your editor or platform opener, e.g. `code` (VS Code), `wslview` or `explorer.exe` (WSL). |

## Security

A **Disclaimer** button is accessible in the dashboard toolbar. It summarizes all security measures in place.

> [!TIP]
> **Active protections**
> - **Bind 127.0.0.1**: invisible from the network
> - **Same-origin only**: the dashboard is served by Flask itself, so no CORS layer is enabled — cross-origin pages get no `Access-Control-Allow-Origin` header and cannot read the API
> - **PID allowlist**: only scanned processes can be killed (403 otherwise)
> - **Container allowlist**: only scanned containers can be acted upon (403 otherwise)
> - **No shell=True**: all commands via subprocess with argument lists
> - **HTML escaping**: XSS protection on all dynamic data
> - **Docker filtering**: processes running inside containers are excluded from the Processes section
> - **Dashboard served by Flask**: no file://, same origin
> - **Virtual environment**: dependencies isolated from system Python

> [!WARNING]
> **Not protected (by design)**
> - No authentication (unnecessary on 127.0.0.1)
> - No TLS (unnecessary on loopback)
> - No rate limiting (local DoS = you DoS yourself)
> - Process command lines may contain visible secrets in the dashboard

## Architecture

```
dev-watch/
├── src/
│   ├── __init__.py
│   ├── config.py          # Shared constants (HOST, PORT)
│   ├── server.py          # Flask app setup, static routes, entrypoint
│   ├── routes.py          # All API route handlers
│   └── helpers.py         # System helpers: process scanning, Docker, network, metrics
├── static/
│   ├── index.html         # Web dashboard (single-file frontend)
│   └── icons/             # 23 local SVG tech icons + logo
├── tests/
│   ├── __init__.py
│   ├── test_api.py        # API/endpoint tests (incl. hermetic parsing + kill/docker paths)
│   └── test_helpers.py    # Unit tests for src/helpers.py
├── start.sh               # Launcher: creates/repairs venv, installs deps, starts server
├── requirements.txt       # Runtime dependencies (flask)
├── requirements-dev.txt   # Dev/test dependencies (pytest)
├── dev-watch.service      # Systemd service file (optional)
├── CHANGELOG.md
├── LICENSE
└── README.md
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard HTML |
| `/icons/<file>` | GET | Local SVG tech icon |
| `/api/ps` | GET | Dev processes + native binaries (excludes containers) |
| `/api/docker` | GET | Docker containers (status, health, ports, compose project) |
| `/api/ports` | GET | All listening TCP ports |
| `/api/connections` | GET | Active TCP connections (ESTABLISHED) |
| `/api/system` | GET | CPU, RAM, disk, GPU |
| `/api/kill` | POST | Kill process (`{"pid": 1234}`) — allowlist only |
| `/api/open` | POST | Open a project folder (`{"path": "/home/..."}`) — allowlist only |
| `/api/docker/stop` | POST | Stop container (`{"id": "abc123"}`) — allowlist only |
| `/api/docker/restart` | POST | Restart container (`{"id": "abc123"}`) — allowlist only |
| `/api/health` | GET | Health check |

## Requirements

- Python 3.8+
- **Linux** (uses `/proc` for process info)
- Docker (optional)
- nvidia-smi (optional, for GPU metrics)

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| **Linux** | Supported | Full support, primary target |
| **WSL2** | Partial | `/proc` and `ss` work. Docker works if Docker Desktop is configured for WSL2. Windows processes are not visible. |
| **macOS** | Not supported | No `/proc`, no `ss`. Would require `lsof`, `sysctl`, different `ps` format. |
| **Windows** | Not supported | All dependencies are Linux-specific. |

> [!NOTE]
> **macOS and Windows support are planned for a future release.** Contributions welcome.

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Commit your changes
4. Push and open a Pull Request

## License

[MIT](LICENSE)

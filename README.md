<p align="center">
  <img src="static/icons/dev-watch-logo.svg" alt="dev-watch logo" width="80" height="80">
</p>

<h1 align="center">DEV WATCH</h1>

<p align="center">
  <strong>v1.0.0</strong> — Local web dashboard to monitor and manage processes, Docker containers, network ports and connections on your dev machine.
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
| ![SVG](https://img.shields.io/badge/SVG_Icons-FFB13B?logo=svg&logoColor=black) | 22 local tech icons from [Dashboard Icons](https://dashboardicons.com/) (zero CDN, served locally) |

## Features

### Processes
- Auto-detection of **Node.js** and **Python** processes (excludes Docker containers)
- Quick filter buttons by type (Node / Python)
- Sortable columns (type, PID, project)
- Kill button (SIGTERM)

### Docker Containers
- Grouped by compose project with accordion
- Health indicator: green (healthy), orange (unhealthy), red (down)
- Auto tech detection from container name (22 icons)
- Image version tag: orange (latest), green (pinned version)
- Host-bound ports (host:container) vs internal-only ports
- Restart / stop buttons

### Network
- **Listening Ports (TCP)**: full machine scan, not just Node/Python
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
1. Creates a Python virtual environment (`.venv/`) if it doesn't exist
2. Installs `flask` and `flask-cors` inside the venv
3. Starts the server on `http://localhost:3999`
4. Opens the dashboard in your browser

Press `Ctrl+C` to stop.

### Systemd (optional, auto-start on boot)

```bash
# Automatically generates the service file with your user and paths
./start.sh install

# To remove
./start.sh uninstall
```

## Security

A **Disclaimer** button is accessible in the dashboard toolbar. It summarizes all security measures in place.

> [!TIP]
> **Active protections**
> - **Bind 127.0.0.1**: invisible from the network
> - **Restricted CORS**: localhost only, no `null`, no `file://`
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
│   ├── server.py          # Flask app setup, static routes, entrypoint
│   ├── routes.py          # All API route handlers
│   └── helpers.py         # System helpers: process scanning, Docker, network, metrics
├── static/
│   ├── index.html         # Web dashboard (single-file frontend)
│   └── icons/             # 22 local SVG tech icons + logo
├── tests/
│   └── test_api.py        # pytest test suite (22 tests)
├── start.sh               # Launcher: creates venv, installs deps, starts server
├── requirements.txt       # Python dependencies
├── dev-watch.service      # Systemd service file (optional)
├── CHANGELOG.md
├── LICENSE
└── README.md
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard HTML |
| `/api/ps` | GET | Node/Python processes (excludes containers) |
| `/api/docker` | GET | Docker containers (status, health, ports, compose project) |
| `/api/ports` | GET | All listening TCP ports |
| `/api/connections` | GET | Active TCP connections (ESTABLISHED) |
| `/api/system` | GET | CPU, RAM, disk, GPU |
| `/api/docker/disk` | GET | Docker disk usage |
| `/api/kill` | POST | Kill process (`{"pid": 1234}`) — allowlist only |
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

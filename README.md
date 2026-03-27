# dev-watch

**v1.0.0** — Local web dashboard to monitor and manage processes, Docker containers, network ports and connections on your dev machine.

> [!CAUTION]
> **This tool is designed for LOCAL USE ONLY.**
> It must NEVER be exposed on a network, VPN, reverse proxy, or the Internet.
> There is no authentication. Anyone who can reach port 3999 can see your processes
> and kill them. Do not change the bind from `127.0.0.1` to `0.0.0.0`.

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

## Security

A **Disclaimer** button is accessible in the dashboard toolbar. It summarizes all security measures in place.

### Active protections
- **Bind 127.0.0.1**: invisible from the network
- **Restricted CORS**: localhost only, no `null`, no `file://`
- **PID allowlist**: only scanned processes can be killed (403 otherwise)
- **Container allowlist**: only scanned containers can be acted upon (403 otherwise)
- **No shell=True**: all commands via subprocess with argument lists
- **HTML escaping**: XSS protection on all dynamic data
- **Docker filtering**: processes running inside containers are excluded from the Processes section
- **Dashboard served by Flask**: no file://, same origin

### Not protected (by design)
- No authentication (unnecessary on 127.0.0.1)
- No TLS (unnecessary on loopback)
- No rate limiting (local DoS = you DoS yourself)
- Process command lines may contain visible secrets in the dashboard

## Architecture

| File | Role |
|------|------|
| `server.py` | Flask server (port 3999): REST API + serves the dashboard |
| `dev-watch.html` | Web interface: consumes the API |
| `icons/` | 22 local SVG icons (tech detection) |
| `start.sh` | Starts the server and opens the browser |
| `dev-watch.service` | Systemd service file (optional) |

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

## Installation

```bash
pip install flask flask-cors --break-system-packages
~/npm-watch/start.sh
```

## Requirements

- Python 3
- Flask + flask-cors
- **Linux** (uses `/proc` for process info)
- Docker (optional)
- nvidia-smi (optional, for GPU)

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| **Linux** | Supported | Full support, primary target |
| **WSL2** | Partial | `/proc` and `ss` work. Docker works if Docker Desktop is configured for WSL2. Windows processes are not visible. |
| **macOS** | Not supported | No `/proc`, no `ss`. Would require `lsof`, `sysctl`, different `ps` format. |
| **Windows** | Not supported | All dependencies are Linux-specific. |

> [!NOTE]
> **macOS and Windows support are planned for a future release.** Contributions welcome.

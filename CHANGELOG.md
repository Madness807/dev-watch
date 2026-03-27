# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-27

### Added
- Process monitoring for Node.js and Python (auto-detection, PID, project name, command, ports, directory)
- Docker container monitoring grouped by compose project with health indicators
- 22 local SVG tech icons with auto-detection from container names (Node, Python, PostgreSQL, Redis, Nginx, etc.)
- Docker image version tags (orange for `latest`, green for pinned versions)
- Docker port display: host-bound (green) vs internal-only (grey)
- Docker restart and stop buttons with confirmation modal
- Full TCP port scan (all listening ports on the machine, not just Node/Python)
- Active TCP connections listing (ESTABLISHED) with process info
- System resource meters in toolbar: CPU, RAM, disk, GPU (nvidia-smi)
- Quick filter buttons (Node / Python) in process section
- Sortable columns (type, PID, project) with visual indicators
- Global text filter across all sections
- Section accordions (collapsible, closed by default)
- In-page toast notifications with structured content and SVG icons
- Sound notifications via Web Audio API (up tone for new, down tone for terminated)
- Configurable watch interval: 3s / 5s / 10s / off
- Status line: green blink (live) / red (watch off)
- Disclaimer modal with security documentation
- Dashboard served by Flask (same origin, no file://)

### Security
- Server bound to 127.0.0.1 only
- CORS restricted to localhost (no `null`, no `file://`)
- PID allowlist: only scanned processes can be killed
- Container allowlist: only scanned containers can be stopped/restarted
- No `shell=True` in subprocess calls
- HTML escaping on all dynamic data (XSS protection)
- Docker process filtering via `/proc/cgroup` (excludes healthcheck noise)
- Zero external network calls (local icons, system fonts, no CDN)
- Virtual environment for dependency isolation

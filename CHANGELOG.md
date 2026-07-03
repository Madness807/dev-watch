# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2026-07-03

### Added
- **Per-process CPU & RAM** in the Processes table. CPU% is instantaneous (sampled between
  scans from `/proc/<pid>/stat` deltas, like `htop`, and can exceed 100% on multi-core
  processes); RAM (resident MB + `%MEM` tooltip) is read from the existing `ps aux` output at
  no extra cost. Both columns are colour-coded (green/amber/red) and sortable — sort by CPU
  or MEM descending to surface the hogs. CPU reads `0%` on the first scan, then real values.

## [1.2.1] - 2026-07-03

### Security
- **CORS**: removed `flask-cors`. The pattern `http://localhost:*` was interpreted as a start-anchored
  regex and accepted **any** origin beginning with `http://localhost` / `http://127.0.0.1`
  (e.g. `http://localhostevil.com`, `http://localhost.evil.com`), letting a malicious page read the
  API and POST to `/api/kill` and the Docker actions. The dashboard is same-origin, so no CORS layer
  is needed.
- **XSS**: `esc()` now escapes quotes, and process/container data is passed to actions via `data-*`
  attributes with delegated listeners instead of inline `onclick`/`title` strings, closing an
  attribute-injection DOM XSS in the command, directory, project-name and compose-label fields.
- `start.sh install` refuses to run as root (`User=root` service); systemd unit adds
  `NoNewPrivileges=true` and `PrivateTmp=true`.
- `/api/kill` now rejects `bool` PIDs explicitly.

### Fixed
- Versioned Python interpreters (`python3.11`, `python3.12`, …) are now classified as `python`
  instead of disappearing from `/api/ps`.
- `start.sh` no longer aborts under `set -e` when `xdg-open` is missing (headless/WSL); the server
  is no longer orphaned and `Ctrl+C` works.
- `run_cmd` / `docker_available` now use a subprocess timeout so a wedged `ss`/`ps`/`docker` cannot
  leak worker threads and child processes indefinitely.
- Listening ports bound to a specific routable IP are now shown (and flagged as exposed) instead of
  being dropped; all PIDs on a shared socket are captured.
- Multi-GPU hosts no longer make `/api/system` return a null GPU block.
- `cwd` prefix checks use a path separator (a sibling dir like `/home/user-evil` no longer matches).
- First dashboard load no longer fires a spurious "Container unhealthy" toast/sound.
- `AbortSignal.timeout()` has a fallback for older browsers.

### Changed
- `/api/ps` runs a single `ss` scan instead of one per process (removes an N+1).
- Dependencies split: `requirements.txt` (runtime: flask) and `requirements-dev.txt` (pytest).
- Shared `HOST`/`PORT` constants in `src/config.py` (no more hardcoded `3999` in `/api/health`).

### Tests
- Added `tests/test_helpers.py` and hermetic (mocked `ps`/`ss`/`docker`) endpoint tests, plus the
  `/api/kill` and Docker-action happy paths and error branches. Suite: 22 → 67 tests.

## [1.2.0] - 2026-03-27

### Added
- **Native binary detection**: compiled ELF binaries (C, C++, Go, Zig, etc.) running from `$HOME` are now detected as type `native` via `/proc/{pid}/exe` + ELF magic bytes check
- Filter button and color-coded tag for native binaries (grey-blue `#90a4ae`)

## [1.1.0] - 2026-03-27

### Added
- Process detection for **Rust** (cargo), **Go** (go run/build/test), **Deno**, **Bun**, **Java** (java/mvn/gradle), **PHP** (php/composer), **Ruby** (ruby/rails/bundle), **C/C++** (gcc/make/cmake/gdb)
- Filter buttons for all 10 languages
- Color-coded type tags for each language
- Python **venv detection**: ENV column shows venv project name (blue) or "system" (grey)
- System service filtering: excludes non-dev processes (firewalld, ProtonVPN, ibus, etc.)
- `./start.sh install` auto-generates and installs systemd service with correct user/paths
- `./start.sh uninstall` removes the systemd service

### Removed
- `/api/docker/disk` endpoint (unused by frontend)

### Fixed
- Process classifier now detects interpreters in venv paths (e.g. `.venv/bin/python3`)
- System services no longer pollute the process list
- dev-watch.service no longer contains hardcoded username/paths

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

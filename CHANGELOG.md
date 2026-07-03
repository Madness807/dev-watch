# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.1] - 2026-07-04

### Fixed
- Process/container lifecycle toasts no longer flap. The scan is an instantaneous `ps` snapshot,
  so any short-lived command run from a directory under `~` (editor hooks, one-off scripts, CLI
  tools) showed up in exactly one scan; the notification diff, keyed on raw PID sets between two
  polls, then fired an endless "New process" / "Process terminated" toast pair on every refresh.
  Appearance and disappearance are now debounced: an item must be seen (or missed) on 2
  consecutive scans before it is announced — processes and containers alike. Trade-off: lifecycle
  toasts arrive one poll interval later.

## [1.6.0] - 2026-07-03

### Added
- **Project Cockpit** (new default view): groups processes + Docker containers + listening ports
  into one card per project, instead of four disconnected tables. Correlation is by canonical
  project directory — a process joins the container whose compose `working_dir` (new
  `com.docker.compose.project.working_dir` label, folded into the existing `docker inspect`) contains
  its resolved `cwd`; ports attach by pid then by published host port. Fine granularity (deepest
  marker among `docker-compose.yml/.git/package.json/pyproject.toml/Cargo.toml/go.mod` wins, so
  `apps/web`/`apps/api` and `-p staging`/`-p prod` stay separate). Unattributable items go to an
  always-visible Ungrouped/Standalone card. New `GET /api/projects` endpoint; correlation lives in a
  pure, hermetically-tested `build_projects()` in `helpers.py`. A persisted **Cockpit | Tables**
  toggle keeps the flat tables one click away. No new attack surface — actions reuse the existing
  allowlist-guarded endpoints.

### Changed
- Refactored `/api/ps`, `/api/docker`, `/api/ports` bodies into reusable `scan_*` functions shared
  by the flat endpoints and `/api/projects`. `/api/ps` items now also carry `project_root`.

## [1.5.1] - 2026-07-03

### Changed
- Split the monolithic `static/index.html` (~1500 lines) into `index.html` (structure),
  `styles.css` and `app.js`, served as-is by Flask (new `/styles.css` and `/app.js` routes).
  Still no build step / bundler. `app.js` stays a classic (non-module) script so the existing
  inline event handlers keep resolving to global functions — pure extraction, no behaviour change.

## [1.5.0] - 2026-07-03

### Added
- **Trend sparklines**: a small inline SVG trend line rendered next to each per-process CPU and
  MEM value, and next to the toolbar CPU/RAM/disk (and GPU) meters. It plots the last ~40 scans so
  a spike is distinguishable from a steady load and a slowly climbing memory leak becomes visible.
  The line is colour-coded by the current value's threshold. History is a client-side ring buffer
  (the server stays stateless) that fills over time and resets on reload — no backend/API change.

## [1.4.0] - 2026-07-03

### Added
- **Quick actions** in the Processes and Listening Ports tables:
  - Click a port to open `http://localhost:<port>` in the browser (`window.open`, no server call).
  - Copy a port's URL (`⧉` button) or the project path (click the directory cell) to the clipboard.
  - **Open the project folder** via a `dir` button → `POST /api/open`, guarded by an allowlist of
    directories seen in the last scan (403 otherwise) and run with a configurable command
    (`DEV_WATCH_OPEN_CMD`, default `xdg-open`; no shell). `/api/ps` now also returns `dir_full`.

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

"""API routes for dev-watch."""

import os
import re
import signal
import json
import time
from flask import jsonify, request
from src.config import PORT, OPEN_CMD
from src.helpers import (
    run_cmd, run_cmd_result, is_in_container, docker_available, get_cwd, get_cmdline, get_venv,
    get_project_name, get_listening_ports, ports_by_pid, first_pid_and_name,
    classify_process, is_native_binary, get_cpu_usage, get_ram_usage,
    get_disk_usage, get_gpu_usage, get_proc_ticks, proc_cpu_percents,
    spawn_detached, path_under, find_project_root, build_projects, MAX_CMD_LEN,
)

# Allowlists: only PIDs/containers/dirs seen by the last scan can be acted upon
known_pids = set()
known_container_ids = set()
known_dirs = set()

# CPU state for delta calculation (mutable container for closure access)
_cpu_state = {"prev": None}

# Per-process CPU state: previous tick snapshot + timestamp for delta computation
_proc_cpu_state = {"ticks": {}, "time": None}

# Docker container IDs are hex; also allow compose-style names. Anchored to an
# alphanumeric first char so a value like "-foo" can never be argument-injected
# into the docker CLI (real short-ids / compose names never start with -/./_).
_DOCKER_ID_RE = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*')


# ── Scanners (return plain lists; reused by the flat endpoints AND /api/projects) ──

def scan_processes():
    """Dev processes with per-process CPU/RAM. Refreshes known_pids / known_dirs."""
    out = run_cmd(["ps", "aux"])
    # Single listening-ports scan reused for every process (no per-PID N+1).
    port_map = ports_by_pid(get_listening_ports())
    processes = []
    seen_pids = set()
    home = os.path.expanduser("~")

    for line in out.splitlines()[1:]:
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        cmd_full = parts[10]

        if "ps aux" in cmd_full:
            continue
        proc_type = classify_process(cmd_full)

        try:
            pid = int(parts[1])
        except ValueError:
            continue

        if pid in seen_pids:
            continue
        seen_pids.add(pid)

        if pid == os.getpid():
            continue
        if is_in_container(pid):
            continue

        cwd = get_cwd(pid)

        # Skip system services (cwd outside home or /tmp)
        if not (path_under(cwd, home) or path_under(cwd, "/tmp")):
            continue

        # Fallback: detect native ELF binaries from user's home
        if not proc_type:
            if is_native_binary(pid):
                proc_type = "native"
            else:
                continue

        cmdline = get_cmdline(pid) or cmd_full

        # Skip system services: commands where the script/module is a system path
        # (but keep user scripts launched with /usr/bin/python3)
        cmd_parts = cmdline.split()
        script_args = [a for a in cmd_parts[1:] if not a.startswith("-")]
        if script_args and any(a.startswith(("/usr/bin/", "/usr/share/", "/usr/sbin/", "/usr/lib/")) for a in script_args):
            continue

        project = get_project_name(cwd, proc_type)
        display_cwd = cwd.replace(home, "~") if cwd != "?" else "?"

        # RAM from the `ps aux` columns we already have (%MEM, RSS in KB).
        try:
            mem_pct = float(parts[3])
            mem_mb = round(int(parts[5]) / 1024)
        except ValueError:
            mem_pct, mem_mb = 0.0, 0

        processes.append({
            "pid": pid,
            "type": proc_type,
            "project": project,
            "cmd": cmdline[:MAX_CMD_LEN],
            "ports": port_map.get(pid, []),
            "dir": display_cwd,
            "dir_full": cwd,
            "project_root": find_project_root(cwd, home) if cwd != "?" else None,
            "venv": get_venv(pid),
            "mem_mb": mem_mb,
            "mem_pct": mem_pct,
        })

    # Instantaneous CPU% per process (delta vs the previous scan).
    ticks_now = get_proc_ticks([p["pid"] for p in processes])
    now = time.monotonic()
    cpu_map = proc_cpu_percents(ticks_now, now, _proc_cpu_state["ticks"], _proc_cpu_state["time"])
    _proc_cpu_state["ticks"] = ticks_now
    _proc_cpu_state["time"] = now
    for p in processes:
        p["cpu"] = cpu_map.get(p["pid"], 0.0)

    processes.sort(key=lambda x: x["type"])
    known_pids.clear()
    known_pids.update(p["pid"] for p in processes)
    known_dirs.clear()
    known_dirs.update(p["dir_full"] for p in processes if p["dir_full"] != "?")
    return processes


def scan_containers():
    """Running Docker containers with compose metadata. Refreshes known_container_ids."""
    if not docker_available():
        return []

    out = run_cmd(["docker", "ps", "--format", "{{json .}}"])
    if not out.strip():
        return []

    ids_out = run_cmd(["docker", "ps", "-q"])
    container_ids = ids_out.strip().splitlines()
    project_map, health_map, workdir_map, service_map = {}, {}, {}, {}
    if container_ids:
        inspect_out = run_cmd(
            ["docker", "inspect", "--format",
             '{{.ID}}|||{{index .Config.Labels "com.docker.compose.project"}}|||'
             '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|||'
             '{{index .Config.Labels "com.docker.compose.project.working_dir"}}|||'
             '{{index .Config.Labels "com.docker.compose.service"}}']
            + container_ids
        )
        for line in inspect_out.strip().splitlines():
            if "|||" in line:
                p = line.split("|||")
                cid = p[0][:12]
                if len(p) >= 2 and p[1]:
                    project_map[cid] = p[1]
                if len(p) >= 3:
                    health_map[cid] = p[2]
                if len(p) >= 4 and p[3]:
                    workdir_map[cid] = p[3]
                if len(p) >= 5 and p[4]:
                    service_map[cid] = p[4]

    containers = []
    for line in out.strip().splitlines():
        try:
            c = json.loads(line)
        except json.JSONDecodeError:
            continue

        cid = c.get("ID", "")
        ports_raw = c.get("Ports", "")
        bound_ports = []
        internal_ports = []
        bound_container = set()
        for m in re.finditer(r':(\d+)->(\d+)', ports_raw):
            bound_ports.append({"host": int(m.group(1)), "container": int(m.group(2))})
            bound_container.add(m.group(2))
        seen = set()
        unique_bound = []
        for p in bound_ports:
            key = (p["host"], p["container"])
            if key not in seen:
                seen.add(key)
                unique_bound.append(p)
        for m in re.finditer(r'(\d+)/(?:tcp|udp)', ports_raw):
            if m.group(1) not in bound_container:
                internal_ports.append(int(m.group(1)))

        # Resolve the compose working_dir to a real POSIX dir, or None (WSL/daemon path).
        raw_workdir = workdir_map.get(cid[:12], "")
        work_dir = os.path.realpath(raw_workdir) if raw_workdir and os.path.isdir(raw_workdir) else None

        containers.append({
            "id": cid,
            "name": c.get("Names", ""),
            "image": c.get("Image", ""),
            "status": c.get("Status", ""),
            "ports": unique_bound,
            "internal_ports": list(set(internal_ports)),
            "project": project_map.get(cid[:12], ""),
            "health": health_map.get(cid[:12], "none"),
            "work_dir": work_dir,
            "service": service_map.get(cid[:12], ""),
        })

    known_container_ids.clear()
    known_container_ids.update(c["id"] for c in containers)
    return containers


def scan_ports():
    """Listening TCP ports (deduped by port number)."""
    ports = []
    seen = set()
    for rec in get_listening_ports():
        port = rec["port"]
        if port in seen:
            continue
        seen.add(port)
        pid = rec["pids"][0] if rec["pids"] else None
        cmd = get_cmdline(pid)[:MAX_CMD_LEN] if pid else ""
        ports.append({
            "port": port,
            "pid": pid,
            "process": rec["process"],
            "cmd": cmd,
            "bind": rec["bind"],
        })
    ports.sort(key=lambda x: x["port"])
    return ports


def register_routes(app):
    """Register all API routes on the Flask app."""

    @app.route("/api/ps")
    def api_ps():
        return jsonify(scan_processes())

    @app.route("/api/docker")
    def api_docker():
        return jsonify(scan_containers())

    @app.route("/api/projects")
    def api_projects():
        home = os.path.expanduser("~")
        # scan_* refresh the allowlists, so cockpit actions work with no extra surface.
        return jsonify(build_projects(scan_processes(), scan_containers(), scan_ports(), home))

    def _docker_action(action):
        data = request.get_json(silent=True)
        container_id = data.get("id") if data else None
        if not container_id or not isinstance(container_id, str):
            return jsonify({"error": "Invalid container ID"}), 400
        if not _DOCKER_ID_RE.fullmatch(container_id):
            return jsonify({"error": "Invalid container ID"}), 400
        if container_id not in known_container_ids:
            return jsonify({"error": "Container not recognized"}), 403
        # Use the real exit code (not "did it print anything") and surface stderr
        # so a failed docker action is diagnosable instead of an opaque 500.
        rc, out, err = run_cmd_result(["docker", action, container_id])
        if rc == 0:
            return jsonify({"ok": True, "id": container_id})
        detail = (err or out or "").strip()
        return jsonify({"error": f"docker {action} failed", "detail": detail}), 500

    @app.route("/api/docker/stop", methods=["POST"])
    def api_docker_stop():
        return _docker_action("stop")

    @app.route("/api/docker/restart", methods=["POST"])
    def api_docker_restart():
        return _docker_action("restart")

    @app.route("/api/kill", methods=["POST"])
    def api_kill():
        data = request.get_json(silent=True)
        pid = data.get("pid") if data else None

        # bool is a subclass of int — reject it explicitly.
        if not isinstance(pid, int) or isinstance(pid, bool):
            return jsonify({"error": "Invalid PID"}), 400
        if pid <= 1 or pid == os.getpid():
            return jsonify({"error": "Protected PID"}), 403
        if pid not in known_pids:
            return jsonify({"error": "PID not recognized"}), 403

        try:
            os.kill(pid, signal.SIGTERM)
            return jsonify({"ok": True, "pid": pid, "signal": "SIGTERM"})
        except ProcessLookupError:
            return jsonify({"error": "Process not found"}), 404
        except PermissionError:
            return jsonify({"error": "Permission denied"}), 403

    @app.route("/api/open", methods=["POST"])
    def api_open():
        data = request.get_json(silent=True)
        path = data.get("path") if data else None
        if not path or not isinstance(path, str):
            return jsonify({"error": "Invalid path"}), 400
        # Only directories surfaced by the last scan may be opened.
        if path not in known_dirs:
            return jsonify({"error": "Directory not recognized"}), 403
        if not os.path.isdir(path):
            return jsonify({"error": "Directory not found"}), 404
        if spawn_detached([OPEN_CMD, path]):
            return jsonify({"ok": True, "path": path})
        return jsonify({"error": f"'{OPEN_CMD}' not found; set DEV_WATCH_OPEN_CMD"}), 500

    @app.route("/api/ports")
    def api_ports():
        return jsonify(scan_ports())

    @app.route("/api/system")
    def api_system():
        cpu_pct, _cpu_state["prev"] = get_cpu_usage(_cpu_state["prev"])
        return jsonify({
            "cpu": cpu_pct,
            "ram": get_ram_usage(),
            "disk": get_disk_usage(),
            "gpu": get_gpu_usage(),
        })

    @app.route("/api/connections")
    def api_connections():
        out = run_cmd(["ss", "-tnp"])
        connections = []
        for line in out.splitlines()[1:]:
            if "ESTAB" not in line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue

            pid, process_name = first_pid_and_name(line)
            connections.append({"local": parts[3], "remote": parts[4], "pid": pid, "process": process_name})

        connections.sort(key=lambda x: x["remote"])
        return jsonify(connections)

    @app.route("/api/health")
    def api_health():
        return jsonify({"status": "ok", "port": PORT})

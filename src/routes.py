"""API routes for dev-watch."""

import os
import re
import signal
import json
import tempfile
import psutil
from flask import jsonify, request
from src.helpers import (
    run_cmd, is_in_container, docker_available, get_cwd, get_venv,
    get_project_name, get_ports_for_pid, classify_process, is_native_binary,
    get_cpu_usage, get_ram_usage, get_disk_usage, get_gpu_usage, MAX_CMD_LEN,
)

# Allowlists: only PIDs/containers seen by the last scan can be acted upon
known_pids = set()
known_container_ids = set()

# CPU state for delta calculation (mutable container for closure access)
_cpu_state = {"prev": None}


def register_routes(app):
    """Register all API routes on the Flask app."""

    @app.route("/api/ps")
    def api_ps():
        processes = []
        seen_pids = set()
        home = os.path.expanduser("~")
        tmp_dir = tempfile.gettempdir()

        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                pid = proc.pid
                if pid in seen_pids:
                    continue
                seen_pids.add(pid)

                if pid == os.getpid():
                    continue

                cmdline_parts = proc.info.get("cmdline") or []
                cmd_full = " ".join(cmdline_parts)
                if not cmd_full:
                    continue

                proc_type = classify_process(cmd_full)

                if is_in_container(pid):
                    continue

                cwd = get_cwd(pid)

                # Skip system services (cwd outside home or tmp)
                if not (cwd.startswith(home) or cwd.startswith(tmp_dir)):
                    continue

                # Fallback: detect native binaries from user's home
                if not proc_type:
                    if is_native_binary(pid):
                        proc_type = "native"
                    else:
                        continue

                # Skip system services: commands where the script/module is a system path
                # (but keep user scripts launched with /usr/bin/python3)
                cmd_parts = cmd_full.split()
                script_args = [a for a in cmd_parts[1:] if not a.startswith("-")]
                if script_args and any(a.startswith(("/usr/bin/", "/usr/share/", "/usr/sbin/", "/usr/lib/")) for a in script_args):
                    continue

                ports = get_ports_for_pid(pid)
                project = get_project_name(cwd, proc_type)
                display_cwd = cwd.replace(home, "~") if cwd != "?" else "?"

                processes.append({
                    "pid": pid,
                    "type": proc_type,
                    "project": project,
                    "cmd": cmd_full[:MAX_CMD_LEN],
                    "ports": ports,
                    "dir": display_cwd,
                    "venv": get_venv(pid),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        processes.sort(key=lambda x: x["type"])
        known_pids.clear()
        known_pids.update(p["pid"] for p in processes)
        return jsonify(processes)

    @app.route("/api/docker")
    def api_docker():
        if not docker_available():
            return jsonify([])

        out = run_cmd(["docker", "ps", "--format", "{{json .}}"])
        if not out.strip():
            return jsonify([])

        ids_out = run_cmd(["docker", "ps", "-q"])
        container_ids = ids_out.strip().splitlines()
        project_map = {}
        health_map = {}
        if container_ids:
            inspect_out = run_cmd(
                ["docker", "inspect", "--format",
                 '{{.ID}}|||{{index .Config.Labels "com.docker.compose.project"}}|||{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}']
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

            containers.append({
                "id": cid,
                "name": c.get("Names", ""),
                "image": c.get("Image", ""),
                "status": c.get("Status", ""),
                "ports": unique_bound,
                "internal_ports": list(set(internal_ports)),
                "project": project_map.get(cid[:12], ""),
                "health": health_map.get(cid[:12], "none"),
            })

        known_container_ids.clear()
        known_container_ids.update(c["id"] for c in containers)
        return jsonify(containers)

    def _docker_action(action):
        data = request.get_json()
        container_id = data.get("id") if data else None
        if not container_id or not isinstance(container_id, str):
            return jsonify({"error": "Invalid container ID"}), 400
        if not re.match(r'^[a-zA-Z0-9_.-]+$', container_id):
            return jsonify({"error": "Invalid container ID"}), 400
        if container_id not in known_container_ids:
            return jsonify({"error": "Container not recognized"}), 403
        result = run_cmd(["docker", action, container_id])
        if result.strip():
            return jsonify({"ok": True, "id": container_id})
        return jsonify({"error": f"Failed: docker {action}"}), 500

    @app.route("/api/docker/stop", methods=["POST"])
    def api_docker_stop():
        return _docker_action("stop")

    @app.route("/api/docker/restart", methods=["POST"])
    def api_docker_restart():
        return _docker_action("restart")

    @app.route("/api/kill", methods=["POST"])
    def api_kill():
        data = request.get_json()
        pid = data.get("pid") if data else None

        if not pid or not isinstance(pid, int):
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

    @app.route("/api/ports")
    def api_ports():
        ports = []
        seen = set()
        try:
            conns = psutil.net_connections(kind="tcp")
        except Exception:
            conns = []

        for conn in conns:
            if conn.status != "LISTEN":
                continue
            if not conn.laddr:
                continue
            port = conn.laddr.port
            if port in seen:
                continue
            seen.add(port)

            pid = conn.pid
            process_name = ""
            cmd = ""
            if pid:
                try:
                    p = psutil.Process(pid)
                    process_name = p.name()
                    cmd = " ".join(p.cmdline())[:MAX_CMD_LEN]
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            bind_ip = conn.laddr.ip
            bind = "local" if bind_ip in ("127.0.0.1", "::1") else "all"

            ports.append({"port": port, "pid": pid, "process": process_name, "cmd": cmd, "bind": bind})

        ports.sort(key=lambda x: x["port"])
        return jsonify(ports)

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
        connections = []
        try:
            conns = psutil.net_connections(kind="tcp")
        except Exception:
            conns = []

        for conn in conns:
            if conn.status != "ESTABLISHED":
                continue
            if not conn.laddr or not conn.raddr:
                continue

            pid = conn.pid
            process_name = ""
            if pid:
                try:
                    process_name = psutil.Process(pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            local = f"{conn.laddr.ip}:{conn.laddr.port}"
            remote = f"{conn.raddr.ip}:{conn.raddr.port}"

            connections.append({"local": local, "remote": remote, "pid": pid, "process": process_name})

        connections.sort(key=lambda x: x["remote"])
        return jsonify(connections)

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "port": 3999})

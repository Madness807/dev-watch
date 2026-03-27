#!/usr/bin/env python3
# ─────────────────────────────────────────────
#  dev-watch — server.py
#  Deps    : pip install flask flask-cors
#  System  : ss (iproute2), docker (optional), nvidia-smi (optional)
#  Launch  : python3 server.py
#  API     : GET  /api/ps             (Node + Python processes)
#            GET  /api/docker         (Docker containers)
#            GET  /api/ports          (listening TCP ports)
#            GET  /api/connections    (active TCP connections)
#            GET  /api/system         (CPU, RAM, disk, GPU)
#            GET  /api/docker/disk    (Docker disk usage)
#            POST /api/kill           {"pid": 1234}
#            POST /api/docker/stop    {"id": "abc123"}
#            POST /api/docker/restart {"id": "abc123"}
#            GET  /api/health
# ─────────────────────────────────────────────

import subprocess
import signal
import os
import re
import json
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=["http://localhost:*", "http://127.0.0.1:*"])

PORT = 3999
MAX_CMD_LEN = 120
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Allowlists: only PIDs/containers seen by the last scan can be acted upon
known_pids = set()
known_container_ids = set()

# ── Static routes ────────────────────────────

@app.route("/")
def serve_dashboard():
    return send_from_directory(BASE_DIR, "dev-watch.html")

@app.route("/icons/<path:filename>")
def serve_icon(filename):
    return send_from_directory(os.path.join(BASE_DIR, "icons"), filename)

# ── Helpers ──────────────────────────────────

def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""

def is_in_container(pid):
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            content = f.read()
            return "docker" in content or "containerd" in content
    except Exception:
        return False

def docker_available():
    try:
        subprocess.check_output(["docker", "info"], stderr=subprocess.DEVNULL, text=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def get_cwd(pid):
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except Exception:
        return "?"

def get_cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\x00", b" ").decode(errors="replace").strip()
    except Exception:
        return ""

def get_project_name(cwd, proc_type):
    if proc_type == "node":
        pkg = os.path.join(cwd, "package.json")
        if os.path.isfile(pkg):
            try:
                with open(pkg) as f:
                    data = json.load(f)
                    return data.get("name", os.path.basename(cwd))
            except Exception:
                pass
    elif proc_type == "python":
        for name in ["setup.py", "pyproject.toml", "setup.cfg"]:
            if os.path.isfile(os.path.join(cwd, name)):
                return os.path.basename(cwd)
    return os.path.basename(cwd) if cwd != "?" else "?"

def get_ports_for_pid(pid):
    ports = []
    out = run_cmd(["ss", "-tlnp"])
    for line in out.splitlines():
        if f"pid={pid}," in line:
            m = re.search(r'(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]|\[::1\]|\*):(\d+)', line)
            if m:
                ports.append(int(m.group(1)))
    return list(set(ports))

def classify_process(cmd_full):
    if re.search(r'(^|\s)(node|npm|npx)(\s|$)|node_modules/\.bin', cmd_full):
        return "node"
    if re.search(r'(^|\s)python[23]?(\s|$)|\.py(\s|$)', cmd_full):
        if "server.py" in cmd_full:
            return None
        return "python"
    return None

def docker_action(action):
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

# ── API routes ───────────────────────────────

@app.route("/api/ps")
def api_ps():
    out = run_cmd(["ps", "aux"])
    processes = []
    seen_pids = set()

    for line in out.splitlines()[1:]:
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        cmd_full = parts[10]

        proc_type = classify_process(cmd_full)
        if not proc_type:
            continue
        if "ps aux" in cmd_full:
            continue

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
        cmdline = get_cmdline(pid) or cmd_full
        ports = get_ports_for_pid(pid)
        project = get_project_name(cwd, proc_type)

        home = os.path.expanduser("~")
        display_cwd = cwd.replace(home, "~") if cwd != "?" else "?"

        processes.append({
            "pid": pid,
            "type": proc_type,
            "project": project,
            "cmd": cmdline[:MAX_CMD_LEN],
            "ports": ports,
            "dir": display_cwd,
        })

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


@app.route("/api/docker/stop", methods=["POST"])
def api_docker_stop():
    return docker_action("stop")

@app.route("/api/docker/restart", methods=["POST"])
def api_docker_restart():
    return docker_action("restart")


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
    out = run_cmd(["ss", "-tlnp"])
    ports = []
    seen = set()
    for line in out.splitlines()[1:]:
        m = re.search(r'(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]|\[::1\]|\*):(\d+)', line)
        if not m:
            continue
        port = int(m.group(1))
        if port in seen:
            continue
        seen.add(port)

        pid_match = re.search(r'pid=(\d+)', line)
        pid = int(pid_match.group(1)) if pid_match else None
        process_name = ""
        cmd = ""
        if pid:
            name_match = re.search(r'\("([^"]+)"', line)
            process_name = name_match.group(1) if name_match else ""
            cmd = get_cmdline(pid)[:MAX_CMD_LEN]

        bind = "all" if ('0.0.0.0' in line or '[::]' in line or '*' in line) else "local"

        ports.append({
            "port": port,
            "pid": pid,
            "process": process_name,
            "cmd": cmd,
            "bind": bind,
        })

    ports.sort(key=lambda x: x["port"])
    return jsonify(ports)


@app.route("/api/system")
def api_system():
    result = {}

    try:
        with open("/proc/stat") as f:
            cpu = f.readline().split()
        idle = int(cpu[4])
        total = sum(int(x) for x in cpu[1:])
        if not hasattr(api_system, '_prev'):
            api_system._prev = (total, idle)
        prev_total, prev_idle = api_system._prev
        dt = total - prev_total
        di = idle - prev_idle
        result["cpu"] = round((1 - di / dt) * 100, 1) if dt > 0 else 0.0
        api_system._prev = (total, idle)
    except Exception:
        result["cpu"] = 0.0

    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                parts = line.split()
                mem[parts[0].rstrip(":")] = int(parts[1])
        total_mb = mem.get("MemTotal", 0) / 1024
        avail_mb = mem.get("MemAvailable", 0) / 1024
        used_mb = total_mb - avail_mb
        result["ram"] = {"used": round(used_mb), "total": round(total_mb), "pct": round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0}
    except Exception:
        result["ram"] = {"used": 0, "total": 0, "pct": 0}

    try:
        st = os.statvfs("/")
        total_gb = (st.f_blocks * st.f_frsize) / (1024**3)
        free_gb = (st.f_bavail * st.f_frsize) / (1024**3)
        used_gb = total_gb - free_gb
        result["disk"] = {"used": round(used_gb, 1), "total": round(total_gb, 1), "pct": round(used_gb / total_gb * 100, 1) if total_gb > 0 else 0}
    except Exception:
        result["disk"] = {"used": 0, "total": 0, "pct": 0}

    gpu_out = run_cmd(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"])
    if gpu_out.strip():
        try:
            parts = gpu_out.strip().split(",")
            result["gpu"] = {"pct": round(float(parts[0].strip()), 1), "vram_used": round(float(parts[1].strip())), "vram_total": round(float(parts[2].strip()))}
        except Exception:
            result["gpu"] = None
    else:
        result["gpu"] = None

    return jsonify(result)


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

        pid_match = re.search(r'pid=(\d+)', line)
        pid = int(pid_match.group(1)) if pid_match else None
        process_name = ""
        if pid:
            name_match = re.search(r'\("([^"]+)"', line)
            process_name = name_match.group(1) if name_match else ""

        connections.append({
            "local": parts[3],
            "remote": parts[4],
            "pid": pid,
            "process": process_name,
        })

    connections.sort(key=lambda x: x["remote"])
    return jsonify(connections)


@app.route("/api/docker/disk")
def api_docker_disk():
    if not docker_available():
        return jsonify([])
    out = run_cmd(["docker", "system", "df", "--format", "{{json .}}"])
    if not out.strip():
        return jsonify([])
    result = []
    for line in out.strip().splitlines():
        try:
            d = json.loads(line)
            result.append({"type": d.get("Type", ""), "total": d.get("TotalCount", 0), "active": d.get("Active", 0), "size": d.get("Size", ""), "reclaimable": d.get("Reclaimable", "")})
        except json.JSONDecodeError:
            continue
    return jsonify(result)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "port": PORT})


# ── Main ─────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    print(f"\n  dev-watch at http://localhost:{PORT}")
    print(f"  Ctrl+C to stop\n")
    app.run(host="127.0.0.1", port=PORT, debug=False)

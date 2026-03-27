#!/usr/bin/env python3
# ─────────────────────────────────────────────
#  dev-watch — server.py
#  Dépendances : pip install flask flask-cors
#  Lancement   : python3 server.py
#  API         : GET  /api/ps
#                GET  /api/docker
#                POST /api/kill       {"pid": 1234}
#                POST /api/docker/stop    {"id": "abc123"}
#                POST /api/docker/restart {"id": "abc123"}
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route("/")
def serve_dashboard():
    return send_from_directory(BASE_DIR, "dev-watch.html")

@app.route("/icons/<path:filename>")
def serve_icon(filename):
    return send_from_directory(os.path.join(BASE_DIR, "icons"), filename)

PORT = 3999

# allowlists — only PIDs/containers seen by the last scan can be acted on
known_pids = set()
known_container_ids = set()

# ── Utilitaires ──────────────────────────────

def run_cmd(cmd):
    """Run a command safely without shell=True. cmd is a list."""
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""

def docker_available():
    """Check if Docker daemon is reachable."""
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

def get_cpu_mem(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            parts = f.read().split()
        utime = int(parts[13])
        stime = int(parts[14])
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    mem_kb = int(line.split()[1])
                    break
            else:
                mem_kb = 0
        hz = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
        cpu_ticks = utime + stime
        with open("/proc/uptime") as f:
            uptime_s = float(f.read().split()[0])
        proc_start = int(parts[21]) / hz
        elapsed = uptime_s - proc_start
        cpu_pct = round((cpu_ticks / hz / elapsed) * 100, 1) if elapsed > 0 else 0.0
        return cpu_pct, round(mem_kb / 1024, 1)
    except Exception:
        return 0.0, 0.0

def classify_process(cmd_full):
    """Retourne le type de processus ou None si non pertinent."""
    if re.search(r'(^|\s)(node|npm|npx)(\s|$)|node_modules/\.bin', cmd_full):
        return "node"
    if re.search(r'(^|\s)python[23]?(\s|$)|\.py(\s|$)', cmd_full):
        if "server.py" in cmd_full:
            return None
        return "python"
    return None

# ── Routes ───────────────────────────────────

@app.route("/api/ps")
def api_ps():
    """Retourne tous les processus Node/npm et Python en cours."""
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
        if "ps aux" in cmd_full or "grep" in cmd_full:
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

        cwd = get_cwd(pid)
        cmdline = get_cmdline(pid) or cmd_full
        cpu, mem = get_cpu_mem(pid)
        ports = get_ports_for_pid(pid)
        project = get_project_name(cwd, proc_type)

        home = os.path.expanduser("~")
        display_cwd = cwd.replace(home, "~") if cwd != "?" else "?"

        processes.append({
            "pid": pid,
            "type": proc_type,
            "project": project,
            "cmd": cmdline[:120],
            "cpu": cpu,
            "mem": mem,
            "ports": ports,
            "dir": display_cwd,
        })

    processes.sort(key=lambda x: x["cpu"], reverse=True)
    known_pids.clear()
    known_pids.update(p["pid"] for p in processes)
    return jsonify(processes)


@app.route("/api/docker")
def api_docker():
    """Retourne les conteneurs Docker en cours."""
    if not docker_available():
        return jsonify([])

    out = run_cmd(["docker", "ps", "--format", "{{json .}}"])
    if not out.strip():
        return jsonify([])

    # health + compose project via inspect
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
        # match host-bound ports (0.0.0.0:8080->8080/tcp)
        bound_container = set()
        for m in re.finditer(r':(\d+)->(\d+)', ports_raw):
            bound_ports.append({"host": int(m.group(1)), "container": int(m.group(2))})
            bound_container.add(m.group(2))
        # deduplicate (same mapping can appear for ipv4 and ipv6)
        seen = set()
        unique_bound = []
        for p in bound_ports:
            key = (p["host"], p["container"])
            if key not in seen:
                seen.add(key)
                unique_bound.append(p)
        # match exposed-only ports (5432/tcp) not already bound
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
    """Stoppe un conteneur Docker par ID."""
    data = request.get_json()
    container_id = data.get("id") if data else None

    if not container_id or not isinstance(container_id, str):
        return jsonify({"error": "ID conteneur invalide"}), 400
    if not re.match(r'^[a-zA-Z0-9_.-]+$', container_id):
        return jsonify({"error": "ID conteneur invalide"}), 400
    if container_id not in known_container_ids:
        return jsonify({"error": "Conteneur non reconnu — rafraichir le dashboard"}), 403

    result = run_cmd(["docker", "stop", container_id])
    if result.strip():
        return jsonify({"ok": True, "id": container_id})
    else:
        return jsonify({"error": "Impossible de stopper le conteneur"}), 500


@app.route("/api/docker/restart", methods=["POST"])
def api_docker_restart():
    """Redemarre un conteneur Docker par ID."""
    data = request.get_json()
    container_id = data.get("id") if data else None

    if not container_id or not isinstance(container_id, str):
        return jsonify({"error": "ID conteneur invalide"}), 400
    if not re.match(r'^[a-zA-Z0-9_.-]+$', container_id):
        return jsonify({"error": "ID conteneur invalide"}), 400
    if container_id not in known_container_ids:
        return jsonify({"error": "Conteneur non reconnu — rafraichir le dashboard"}), 403

    result = run_cmd(["docker", "restart", container_id])
    if result.strip():
        return jsonify({"ok": True, "id": container_id})
    else:
        return jsonify({"error": "Impossible de redemarrer le conteneur"}), 500


@app.route("/api/kill", methods=["POST"])
def api_kill():
    """Envoie SIGTERM au PID."""
    data = request.get_json()
    pid = data.get("pid") if data else None

    if not pid or not isinstance(pid, int):
        return jsonify({"error": "PID invalide"}), 400
    if pid <= 1 or pid == os.getpid():
        return jsonify({"error": "PID protege"}), 403
    if pid not in known_pids:
        return jsonify({"error": "PID non reconnu — rafraichir le dashboard"}), 403

    try:
        os.kill(pid, signal.SIGTERM)
        return jsonify({"ok": True, "pid": pid, "signal": "SIGTERM"})
    except ProcessLookupError:
        return jsonify({"error": "Processus introuvable"}), 404
    except PermissionError:
        return jsonify({"error": "Permission refusee"}), 403


@app.route("/api/ports")
def api_ports():
    """Liste tous les ports TCP en ecoute sur la machine."""
    out = run_cmd(["ss", "-tlnp"])
    ports = []
    seen = set()
    for line in out.splitlines()[1:]:
        # parse address:port
        m = re.search(r'(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]|\[::1\]|\*):(\d+)', line)
        if not m:
            continue
        port = int(m.group(1))
        if port in seen:
            continue
        seen.add(port)

        # parse process info
        pid_match = re.search(r'pid=(\d+)', line)
        pid = int(pid_match.group(1)) if pid_match else None
        process_name = ""
        cmd = ""
        if pid:
            name_match = re.search(r'\("([^"]+)"', line)
            process_name = name_match.group(1) if name_match else ""
            cmd = get_cmdline(pid)[:80]

        # determine bind type
        if '0.0.0.0' in line or '[::]' in line or '*' in line:
            bind = "all"
        else:
            bind = "local"

        ports.append({
            "port": port,
            "pid": pid,
            "process": process_name,
            "cmd": cmd,
            "bind": bind,
        })

    ports.sort(key=lambda x: x["port"])
    return jsonify(ports)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "port": PORT})


# ── Main ─────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    print(f"\n  dev-watch server sur http://localhost:{PORT}")
    print(f"  API : GET  /api/ps       (Node + Python)")
    print(f"        GET  /api/docker   (conteneurs)")
    print(f"        POST /api/kill     {{\"pid\": 1234}}")
    print(f"        POST /api/docker/stop    {{\"id\": \"abc\"}}")
    print(f"        POST /api/docker/restart {{\"id\": \"abc\"}}")
    print(f"  Ctrl+C pour arreter\n")
    app.run(host="127.0.0.1", port=PORT, debug=False)

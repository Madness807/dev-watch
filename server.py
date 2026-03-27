#!/usr/bin/env python3
# ─────────────────────────────────────────────
#  npm-watch — server.py
#  Dépendances : pip install flask flask-cors
#  Lancement   : python3 server.py
#  API         : GET  /api/ps
#                POST /api/kill  {"pid": 1234}
# ─────────────────────────────────────────────

import subprocess
import signal
import os
import re
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=["http://localhost:*", "http://127.0.0.1:*", "null"])  # null = fichier local ouvert en file://

PORT = 3999

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

def get_project_name(cwd):
    pkg = os.path.join(cwd, "package.json")
    if os.path.isfile(pkg):
        try:
            import json
            with open(pkg) as f:
                data = json.load(f)
                return data.get("name", os.path.basename(cwd))
        except Exception:
            pass
    return os.path.basename(cwd) if cwd != "?" else "?"

def get_ports_for_pid(pid):
    """Retourne la liste des ports TCP en écoute pour un PID donné."""
    ports = []
    out = run_cmd(["ss", "-tlnp"])
    for line in out.splitlines():
        if f"pid={pid}," in line:
            m = re.search(r':(\d+)\s', line.split("Local")[0] if "Local" in line else line)
            # cherche le port dans l'adresse locale
            m = re.search(r'(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]):(\d+)', line)
            if m:
                ports.append(int(m.group(1)))
    return list(set(ports))

def get_cpu_mem(pid):
    """Lit CPU% et MEM(MB) depuis /proc."""
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
        # CPU approximatif : ticks / Hz (pas de mesure delta ici, valeur brute)
        hz = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
        cpu_ticks = utime + stime
        uptime_s = float(open("/proc/uptime").read().split()[0])
        proc_start = int(parts[21]) / hz
        elapsed = uptime_s - proc_start
        cpu_pct = round((cpu_ticks / hz / elapsed) * 100, 1) if elapsed > 0 else 0.0
        return cpu_pct, round(mem_kb / 1024, 1)
    except Exception:
        return 0.0, 0.0

# ── Routes ───────────────────────────────────

@app.route("/api/ps")
def api_ps():
    """Retourne tous les processus Node/npm en cours."""
    out = run_cmd(["ps", "aux"])
    processes = []
    seen_pids = set()

    for line in out.splitlines()[1:]:
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        cmd_full = parts[10]
        # filtre : node, npm, npx ou binaires node_modules
        if not re.search(r'(^|\s)(node|npm|npx)(\s|$)|node_modules/\.bin', cmd_full):
            continue
        # exclut les lignes grep elles-mêmes
        if "ps aux" in cmd_full or "grep" in cmd_full:
            continue

        try:
            pid = int(parts[1])
        except ValueError:
            continue

        if pid in seen_pids:
            continue
        seen_pids.add(pid)

        cwd = get_cwd(pid)
        cmdline = get_cmdline(pid) or cmd_full
        cpu, mem = get_cpu_mem(pid)
        ports = get_ports_for_pid(pid)
        project = get_project_name(cwd)

        # raccourcit le chemin home
        home = os.path.expanduser("~")
        display_cwd = cwd.replace(home, "~") if cwd != "?" else "?"

        processes.append({
            "pid": pid,
            "project": project,
            "cmd": cmdline[:80],
            "cpu": cpu,
            "mem": mem,
            "ports": ports,
            "dir": display_cwd,
        })

    # tri par CPU desc
    processes.sort(key=lambda x: x["cpu"], reverse=True)
    return jsonify(processes)


@app.route("/api/kill", methods=["POST"])
def api_kill():
    """Envoie SIGTERM au PID, puis SIGKILL si résistant."""
    data = request.get_json()
    pid = data.get("pid") if data else None

    if not pid or not isinstance(pid, int):
        return jsonify({"error": "PID invalide"}), 400

    # Sécurité : on refuse de tuer PID 1 ou notre propre process
    if pid <= 1 or pid == os.getpid():
        return jsonify({"error": "PID protégé"}), 403

    try:
        os.kill(pid, signal.SIGTERM)
        return jsonify({"ok": True, "pid": pid, "signal": "SIGTERM"})
    except ProcessLookupError:
        return jsonify({"error": "Processus introuvable"}), 404
    except PermissionError:
        return jsonify({"error": "Permission refusée"}), 403


@app.route("/api/docker")
def api_docker():
    """Retourne les conteneurs Docker en cours avec leur statut."""
    if not docker_available():
        return jsonify([])

    ids_out = run_cmd(["docker", "ps", "-q"])
    container_ids = ids_out.strip().splitlines()
    if not container_ids:
        return jsonify([])

    inspect_out = run_cmd(
        ["docker", "inspect", "--format",
         '{{.ID}}|||{{index .Config.Labels "com.docker.compose.project"}}|||{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}']
        + container_ids
    )

    containers = []
    for line in inspect_out.strip().splitlines():
        parts = line.split("|||")
        if len(parts) == 3:
            containers.append({
                "id": parts[0][:12],
                "project": parts[1] or "unknown",
                "health": parts[2],
            })
    return jsonify(containers)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "port": PORT})


# ── Main ─────────────────────────────────────

if __name__ == "__main__":
    print(f"\n  npm-watch server démarré sur http://localhost:{PORT}")
    print(f"  API : GET  /api/ps")
    print(f"        POST /api/kill  {{\"pid\": 1234}}")
    print(f"  Ctrl+C pour arrêter\n")
    app.run(host="127.0.0.1", port=PORT, debug=False)

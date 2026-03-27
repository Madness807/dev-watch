"""System helpers for dev-watch. Process scanning, Docker, network, metrics."""

import subprocess
import os
import re
import sys
import json
import psutil

MAX_CMD_LEN = 120

IS_WINDOWS = sys.platform == "win32"


def run_cmd(cmd):
    """Run a command safely without shell=True. cmd is a list."""
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def is_in_container(pid):
    """Check if a PID runs inside a Docker container."""
    if IS_WINDOWS:
        return False
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            content = f.read()
            return "docker" in content or "containerd" in content
    except Exception:
        return False


def docker_available():
    """Check if Docker daemon is reachable."""
    try:
        subprocess.check_output(["docker", "info"], stderr=subprocess.DEVNULL, text=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_venv(pid):
    """Detect if a process runs inside a Python venv. Returns venv name or None."""
    try:
        cmdline = psutil.Process(pid).cmdline()
        argv0 = cmdline[0] if cmdline else ""
        if argv0 and not os.path.isabs(argv0):
            cwd = get_cwd(pid)
            if cwd != "?":
                argv0 = os.path.join(cwd, argv0)
    except Exception:
        return None
    # Normalize path separators for cross-platform matching
    argv0 = argv0.replace("\\", "/")
    for marker in ("/.venv/", "/venv/", "/virtualenv/", "/.env/"):
        if marker in argv0:
            venv_idx = argv0.index(marker)
            project_path = argv0[:venv_idx]
            return os.path.basename(project_path)
    return None


def get_cwd(pid):
    try:
        return psutil.Process(pid).cwd()
    except Exception:
        return "?"


def get_cmdline(pid):
    try:
        parts = psutil.Process(pid).cmdline()
        return " ".join(parts).strip()
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
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.pid == pid and conn.status == "LISTEN" and conn.laddr:
                ports.append(conn.laddr.port)
    except Exception:
        pass
    return list(set(ports))


def classify_process(cmd_full):
    """Return process type or None."""
    # Node.js
    if re.search(r'(^|\s|/)(node|npm|npx)(\s|$)|node_modules/\.bin', cmd_full):
        return "node"
    # Python
    if re.search(r'(^|\s|/)python[23]?(\s|$)|\.py(\s|$)', cmd_full):
        if "server.py" in cmd_full:
            return None
        return "python"
    # Rust (cargo commands or binaries in target/)
    if re.search(r'(^|\s|/)cargo(\s|$)|/target/(debug|release)/', cmd_full):
        return "rust"
    # Go (go run/build/test or go tool)
    if re.search(r'(^|\s|/)go(\s+)(run|build|test|install|vet)(\s|$)', cmd_full):
        return "go"
    # Deno
    if re.search(r'(^|\s|/)deno(\s|$)', cmd_full):
        return "deno"
    # Bun
    if re.search(r'(^|\s|/)bun(\s|$)', cmd_full):
        return "bun"
    # Java
    if re.search(r'(^|\s|/)(java|mvn|gradle|mvnw|gradlew)(\s|$)', cmd_full):
        return "java"
    # PHP
    if re.search(r'(^|\s|/)(php|composer)(\s|$)|\.php(\s|$)', cmd_full):
        return "php"
    # Ruby
    if re.search(r'(^|\s|/)(ruby|rails|bundle|rake)(\s|$)|\.rb(\s|$)', cmd_full):
        return "ruby"
    # C/C++ (build tools and debugger)
    if re.search(r'(^|\s|/)(gcc|g\+\+|make|cmake|gdb|clang|clang\+\+)(\s|$)', cmd_full):
        return "c"
    return None


def is_native_binary(pid):
    """Check if a PID is a native binary running from user's home."""
    try:
        exe = psutil.Process(pid).exe()
    except Exception:
        return False
    home = os.path.expanduser("~")
    if not exe.startswith(home):
        return False
    if IS_WINDOWS:
        return exe.lower().endswith(".exe")
    # Check ELF magic bytes on Linux/macOS
    try:
        with open(exe, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except Exception:
        return False


# ── System metrics ──

def get_cpu_usage(prev_state):
    """Return (cpu_pct, new_state). Pass None for first call."""
    try:
        pct = psutil.cpu_percent(interval=None)
        return round(pct, 1), True
    except Exception:
        return 0.0, prev_state


def get_ram_usage():
    try:
        mem = psutil.virtual_memory()
        total_mb = mem.total / (1024 * 1024)
        used_mb = (mem.total - mem.available) / (1024 * 1024)
        return {"used": round(used_mb), "total": round(total_mb), "pct": round(mem.percent, 1)}
    except Exception:
        return {"used": 0, "total": 0, "pct": 0}


def get_disk_usage():
    try:
        path = "C:\\" if IS_WINDOWS else "/"
        disk = psutil.disk_usage(path)
        total_gb = disk.total / (1024 ** 3)
        used_gb = disk.used / (1024 ** 3)
        return {"used": round(used_gb, 1), "total": round(total_gb, 1), "pct": round(disk.percent, 1)}
    except Exception:
        return {"used": 0, "total": 0, "pct": 0}


def get_gpu_usage():
    out = run_cmd(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"])
    if out.strip():
        try:
            parts = out.strip().split(",")
            return {"pct": round(float(parts[0].strip()), 1), "vram_used": round(float(parts[1].strip())), "vram_total": round(float(parts[2].strip()))}
        except Exception:
            return None
    return None

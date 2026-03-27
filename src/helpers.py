"""System helpers for dev-watch. Process scanning, Docker, network, metrics."""

import subprocess
import os
import re
import json

MAX_CMD_LEN = 120


def run_cmd(cmd):
    """Run a command safely without shell=True. cmd is a list."""
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def is_in_container(pid):
    """Check if a PID runs inside a Docker container via /proc cgroup."""
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
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            argv0 = f.read().split(b"\x00")[0].decode(errors="replace")
        # If relative path, resolve via cwd
        if not argv0.startswith("/"):
            cwd = get_cwd(pid)
            if cwd != "?":
                argv0 = os.path.join(cwd, argv0)
    except Exception:
        return None
    for marker in ("/.venv/", "/venv/", "/virtualenv/", "/.env/"):
        if marker in argv0:
            venv_idx = argv0.index(marker)
            project_path = argv0[:venv_idx]
            return os.path.basename(project_path)
    return None


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


# ── System metrics ──

def get_cpu_usage(prev_state):
    """Return (cpu_pct, new_state). Pass None for first call."""
    try:
        with open("/proc/stat") as f:
            cpu = f.readline().split()
        idle = int(cpu[4])
        total = sum(int(x) for x in cpu[1:])
        if prev_state is None:
            return 0.0, (total, idle)
        prev_total, prev_idle = prev_state
        dt = total - prev_total
        di = idle - prev_idle
        pct = round((1 - di / dt) * 100, 1) if dt > 0 else 0.0
        return pct, (total, idle)
    except Exception:
        return 0.0, prev_state


def get_ram_usage():
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                parts = line.split()
                mem[parts[0].rstrip(":")] = int(parts[1])
        total_mb = mem.get("MemTotal", 0) / 1024
        avail_mb = mem.get("MemAvailable", 0) / 1024
        used_mb = total_mb - avail_mb
        return {"used": round(used_mb), "total": round(total_mb), "pct": round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0}
    except Exception:
        return {"used": 0, "total": 0, "pct": 0}


def get_disk_usage():
    try:
        st = os.statvfs("/")
        total_gb = (st.f_blocks * st.f_frsize) / (1024**3)
        free_gb = (st.f_bavail * st.f_frsize) / (1024**3)
        used_gb = total_gb - free_gb
        return {"used": round(used_gb, 1), "total": round(total_gb, 1), "pct": round(used_gb / total_gb * 100, 1) if total_gb > 0 else 0}
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

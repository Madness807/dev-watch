"""System helpers for dev-watch. Process scanning, Docker, network, metrics."""

import subprocess
import os
import re
import json

MAX_CMD_LEN = 120
CMD_TIMEOUT = 5  # seconds; bounds a wedged external binary (ss/ps/docker)

_EMPTY_USAGE = {"used": 0, "total": 0, "pct": 0}


def run_cmd(cmd):
    """Run a command safely without shell=True. cmd is a list.

    Returns the command's stdout, or "" on failure/timeout. A timeout guards
    against a hung external binary (e.g. docker while the daemon restarts)
    permanently blocking a worker thread and leaking child processes.
    """
    try:
        return subprocess.check_output(
            cmd, stderr=subprocess.DEVNULL, text=True, timeout=CMD_TIMEOUT
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def spawn_detached(cmd):
    """Launch cmd (a list) fire-and-forget, detached from the server process.

    Returns True if spawned, False if the binary is missing. Does not wait, so a
    GUI opener (file manager / editor) does not block the request.
    """
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except (FileNotFoundError, OSError):
        return False


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
        subprocess.check_output(
            ["docker", "info"], stderr=subprocess.DEVNULL, text=True, timeout=CMD_TIMEOUT
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
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
    for marker in ("/.venv/", "/venv/", "/virtualenv/"):
        if marker in argv0:
            venv_idx = argv0.index(marker)
            project_path = argv0[:venv_idx]
            return os.path.basename(project_path) or None
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


# ── Listening ports (single `ss -tlnp` scan, shared by /api/ps and /api/ports) ──

# host:port at the local-address column — captures 0.0.0.0, 127.0.0.1, [::],
# [::1], * and specific routable IPs (previously only wildcard/loopback matched).
_LOCAL_ADDR_RE = re.compile(r'^(.*):(\d+)$')
_PID_RE = re.compile(r'pid=(\d+)')
_PROC_NAME_RE = re.compile(r'\("([^"]+)"')


def parse_listening_ports(out):
    """Parse `ss -tlnp` output into records: {port, pids, process, bind}."""
    records = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        m = _LOCAL_ADDR_RE.match(parts[3])  # Local Address:Port column
        if not m:
            continue
        host, port = m.group(1), int(m.group(2))
        is_local = host in ("127.0.0.1", "[::1]") or host.startswith("127.")
        pids = [int(p) for p in _PID_RE.findall(line)]
        name_m = _PROC_NAME_RE.search(line)
        records.append({
            "port": port,
            "pids": pids,
            "process": name_m.group(1) if name_m else "",
            "bind": "local" if is_local else "all",
        })
    return records


def get_listening_ports():
    return parse_listening_ports(run_cmd(["ss", "-tlnp"]))


def ports_by_pid(records):
    """Map pid -> sorted list of listening ports, from parsed records."""
    mapping = {}
    for r in records:
        for pid in r["pids"]:
            mapping.setdefault(pid, set()).add(r["port"])
    return {pid: sorted(ports) for pid, ports in mapping.items()}


def first_pid_and_name(line):
    """Extract the first (pid, process_name) from an `ss` line, or (None, "")."""
    pid_m = _PID_RE.search(line)
    name_m = _PROC_NAME_RE.search(line)
    return (
        int(pid_m.group(1)) if pid_m else None,
        name_m.group(1) if name_m else "",
    )


def classify_process(cmd_full):
    """Return process type or None."""
    # Node.js
    if re.search(r'(^|\s|/)(node|npm|npx)(\s|$)|node_modules/\.bin', cmd_full):
        return "node"
    # Python (incl. versioned interpreters: python3.11, python3.12, ...)
    if re.search(r'(^|\s|/)python(\d+(\.\d+)?)?(\s|$)|\.py(\s|$)', cmd_full):
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


# ── Per-process CPU (instantaneous, sampled between scans like htop) ──

CLK_TCK = os.sysconf("SC_CLK_TCK")  # clock ticks per second (usually 100)


def read_proc_ticks(pid):
    """CPU time (utime+stime, in clock ticks) for a PID from /proc/<pid>/stat.

    Returns None if unreadable. The comm field (field 2) is wrapped in parens
    and may itself contain spaces or ')', so fields are read after the last ')'.
    """
    try:
        with open(f"/proc/{pid}/stat") as f:
            content = f.read()
        fields = content[content.rindex(")") + 2:].split()
        return int(fields[11]) + int(fields[12])  # utime (field 14) + stime (field 15)
    except Exception:
        return None


def get_proc_ticks(pids):
    """Map pid -> CPU ticks for the given pids (skips unreadable ones)."""
    ticks = {}
    for pid in pids:
        t = read_proc_ticks(pid)
        if t is not None:
            ticks[pid] = t
    return ticks


def proc_cpu_percents(ticks_now, now, prev_ticks, prev_time):
    """Instantaneous CPU% per pid from two tick snapshots.

    %CPU = 100 * Δticks / (CLK_TCK * Δseconds) — per-core, so a process using
    more than one core can exceed 100%. Returns 0.0 on the first sample (no
    baseline) or for a pid unseen last time.
    """
    if prev_time is None or now <= prev_time:
        return {pid: 0.0 for pid in ticks_now}
    dt = now - prev_time
    out = {}
    for pid, t in ticks_now.items():
        prev = prev_ticks.get(pid)
        if prev is None:
            out[pid] = 0.0
        else:
            out[pid] = round(max((t - prev) / CLK_TCK / dt * 100, 0.0), 1)
    return out


def is_native_binary(pid):
    """Check if a PID is a native ELF binary running from user's home."""
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except Exception:
        return False
    home = os.path.expanduser("~")
    if not (exe == home or exe.startswith(home + os.sep)):
        return False
    # Check ELF magic bytes
    try:
        with open(exe, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except Exception:
        return False


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
        return dict(_EMPTY_USAGE)


def get_disk_usage():
    try:
        st = os.statvfs("/")
        total_gb = (st.f_blocks * st.f_frsize) / (1024**3)
        free_gb = (st.f_bavail * st.f_frsize) / (1024**3)
        used_gb = total_gb - free_gb
        return {"used": round(used_gb, 1), "total": round(total_gb, 1), "pct": round(used_gb / total_gb * 100, 1) if total_gb > 0 else 0}
    except Exception:
        return dict(_EMPTY_USAGE)


def get_gpu_usage():
    out = run_cmd(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"])
    if out.strip():
        try:
            # First GPU only (multi-GPU hosts print one line per device).
            parts = out.strip().splitlines()[0].split(",")
            return {"pct": round(float(parts[0].strip()), 1), "vram_used": round(float(parts[1].strip())), "vram_total": round(float(parts[2].strip()))}
        except Exception:
            return None
    return None

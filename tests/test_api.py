"""API tests for dev-watch server."""

import os

import pytest
from src import routes
from src.server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def clean_allowlists():
    """Isolate the module-global PID/container allowlists between tests."""
    routes.known_pids.clear()
    routes.known_container_ids.clear()
    yield
    routes.known_pids.clear()
    routes.known_container_ids.clear()


# ── Health ──

def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["port"] == 3999


# ── Dashboard ──

def test_dashboard_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"DEV WATCH" in res.data


# ── Processes ──

def test_ps_returns_list(client):
    res = client.get("/api/ps")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)


def test_ps_entries_have_required_fields(client):
    res = client.get("/api/ps")
    data = res.get_json()
    required = {"pid", "type", "project", "cmd", "ports", "dir", "cpu", "mem_mb", "mem_pct"}
    for proc in data:
        assert required.issubset(proc.keys()), f"Missing fields in {proc}"
        assert proc["type"] in ("node", "python", "rust", "go", "deno", "bun", "java", "php", "ruby", "c", "native")
        assert isinstance(proc["pid"], int)
        assert isinstance(proc["ports"], list)


# ── Docker ──

def test_docker_returns_list(client):
    res = client.get("/api/docker")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)


def test_docker_entries_have_required_fields(client):
    res = client.get("/api/docker")
    data = res.get_json()
    required = {"id", "name", "image", "status", "ports", "internal_ports", "project", "health"}
    for container in data:
        assert required.issubset(container.keys()), f"Missing fields in {container}"


# ── Ports ──

def test_ports_returns_list(client):
    res = client.get("/api/ports")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)


def test_ports_entries_have_required_fields(client):
    res = client.get("/api/ports")
    data = res.get_json()
    required = {"port", "pid", "process", "cmd", "bind"}
    for p in data:
        assert required.issubset(p.keys()), f"Missing fields in {p}"
        assert p["bind"] in ("all", "local")
        assert isinstance(p["port"], int)


def test_ports_sorted_by_port_number(client):
    res = client.get("/api/ports")
    data = res.get_json()
    ports = [p["port"] for p in data]
    assert ports == sorted(ports)


# ── Connections ──

def test_connections_returns_list(client):
    res = client.get("/api/connections")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)


def test_connections_entries_have_required_fields(client):
    res = client.get("/api/connections")
    data = res.get_json()
    required = {"local", "remote", "pid", "process"}
    for conn in data:
        assert required.issubset(conn.keys()), f"Missing fields in {conn}"


# ── System ──

def test_system_returns_metrics(client):
    res = client.get("/api/system")
    assert res.status_code == 200
    data = res.get_json()
    assert "cpu" in data
    assert "ram" in data
    assert "disk" in data
    assert isinstance(data["ram"]["pct"], (int, float))
    assert isinstance(data["disk"]["pct"], (int, float))


# ── Kill security ──

def test_kill_rejects_invalid_pid(client):
    res = client.post("/api/kill", json={"pid": "abc"})
    assert res.status_code == 400


def test_kill_rejects_pid_1(client):
    res = client.post("/api/kill", json={"pid": 1})
    assert res.status_code == 403


def test_kill_rejects_unknown_pid(client):
    res = client.post("/api/kill", json={"pid": 999999})
    assert res.status_code == 403
    data = res.get_json()
    assert "not recognized" in data["error"].lower()


def test_kill_rejects_no_body(client):
    res = client.post("/api/kill", content_type="application/json", data="{}")
    assert res.status_code == 400


# ── Docker actions security ──

def test_docker_stop_rejects_unknown_id(client):
    res = client.post("/api/docker/stop", json={"id": "fakeid123"})
    assert res.status_code == 403


def test_docker_restart_rejects_unknown_id(client):
    res = client.post("/api/docker/restart", json={"id": "fakeid123"})
    assert res.status_code == 403


def test_docker_stop_rejects_invalid_id(client):
    res = client.post("/api/docker/stop", json={"id": "../../../etc"})
    assert res.status_code == 400


def test_docker_stop_rejects_no_body(client):
    res = client.post("/api/docker/stop", content_type="application/json", data="{}")
    assert res.status_code == 400


# ── Icons ──

def test_icon_served(client):
    res = client.get("/icons/docker.svg")
    assert res.status_code == 200
    assert b"<svg" in res.data


def test_icon_404(client):
    res = client.get("/icons/nonexistent.svg")
    assert res.status_code == 404


def test_icon_path_traversal_blocked(client):
    for path in ["/icons/../server.py", "/icons/%2e%2e/server.py", "/icons/..%2fserver.py"]:
        res = client.get(path)
        assert res.status_code != 200, path
        assert b"Flask" not in res.data


# ── CORS removed (same-origin only) ──

def test_no_cors_header_for_any_origin(client):
    # flask-cors was removed; the dashboard is same-origin, so NO origin — not
    # even a real localhost:port — should ever receive an ACAO header.
    for origin in ["http://localhost.evil.com", "http://localhostevil.com", "http://localhost:3000"]:
        res = client.get("/api/ps", headers={"Origin": origin})
        assert res.headers.get("Access-Control-Allow-Origin") is None, origin


# ── Kill happy path + error branches (monkeypatched os.kill) ──

def test_kill_success(client, monkeypatch):
    routes.known_pids.add(4242)
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
    res = client.post("/api/kill", json={"pid": 4242})
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] and body["pid"] == 4242 and body["signal"] == "SIGTERM"


def test_kill_process_not_found_returns_404(client, monkeypatch):
    routes.known_pids.add(4243)

    def boom(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(os, "kill", boom)
    res = client.post("/api/kill", json={"pid": 4243})
    assert res.status_code == 404


def test_kill_permission_denied_returns_403(client, monkeypatch):
    routes.known_pids.add(4244)

    def boom(pid, sig):
        raise PermissionError()

    monkeypatch.setattr(os, "kill", boom)
    res = client.post("/api/kill", json={"pid": 4244})
    assert res.status_code == 403


def test_kill_rejects_bool_pid(client):
    # bool is a subclass of int — must not be accepted as a PID.
    res = client.post("/api/kill", json={"pid": True})
    assert res.status_code == 400


# ── Docker action happy path + failure branch ──

def test_docker_stop_success(client, monkeypatch):
    routes.known_container_ids.add("abc123def456")
    monkeypatch.setattr(routes, "run_cmd", lambda cmd: "abc123def456\n")
    res = client.post("/api/docker/stop", json={"id": "abc123def456"})
    assert res.status_code == 200
    assert res.get_json()["ok"]


def test_docker_stop_failure_returns_500(client, monkeypatch):
    routes.known_container_ids.add("abc123def456")
    monkeypatch.setattr(routes, "run_cmd", lambda cmd: "")  # docker printed nothing
    res = client.post("/api/docker/stop", json={"id": "abc123def456"})
    assert res.status_code == 500


# ── Hermetic parsing tests (canned ss/ps output) ──

def test_ports_hermetic_parsing(client, monkeypatch):
    from src import helpers
    ss_out = (
        "State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
        'LISTEN 0 511 0.0.0.0:8080 0.0.0.0:* users:(("nginx",pid=10,fd=6))\n'
        'LISTEN 0 128 127.0.0.1:5432 0.0.0.0:* users:(("postgres",pid=20,fd=5))\n'
        'LISTEN 0 128 192.168.1.5:3000 0.0.0.0:* users:(("node",pid=30,fd=7))\n'
    )
    monkeypatch.setattr(helpers, "run_cmd", lambda cmd: ss_out if cmd[:2] == ["ss", "-tlnp"] else "")
    monkeypatch.setattr(routes, "get_cmdline", lambda pid: "")
    data = {p["port"]: p for p in client.get("/api/ports").get_json()}
    assert data[8080]["bind"] == "all" and data[8080]["process"] == "nginx"
    assert data[5432]["bind"] == "local"
    assert data[3000]["bind"] == "all"   # specific-IP bind now surfaced


def test_connections_hermetic_parsing(client, monkeypatch):
    ss_out = (
        "State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
        'ESTAB 0 0 127.0.0.1:5432 127.0.0.1:54321 users:(("postgres",pid=20,fd=9))\n'
        'ESTAB 0 0 192.168.1.5:44300 1.2.3.4:443 users:(("curl",pid=99,fd=3))\n'
    )
    monkeypatch.setattr(routes, "run_cmd", lambda cmd: ss_out if cmd[:2] == ["ss", "-tnp"] else "")
    conns = {c["remote"]: c for c in client.get("/api/connections").get_json()}
    assert conns["1.2.3.4:443"]["process"] == "curl"
    assert conns["1.2.3.4:443"]["pid"] == 99


def test_ps_hermetic_parsing(client, monkeypatch):
    from src import helpers
    home = os.path.expanduser("~")
    ps_out = (
        "USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND\n"
        "me 4242 0.1 0.2 100 200 ? Sl 10:00 0:01 node /home/x/app/index.js\n"
    )
    ss_out = (
        "State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
        'LISTEN 0 511 127.0.0.1:3000 0.0.0.0:* users:(("node",pid=4242,fd=20))\n'
    )

    def fake(cmd):
        joined = " ".join(cmd)
        if joined.startswith("ps aux"):
            return ps_out
        if joined.startswith("ss -tlnp"):
            return ss_out
        return ""

    monkeypatch.setattr(routes, "run_cmd", fake)
    monkeypatch.setattr(helpers, "run_cmd", fake)
    monkeypatch.setattr(routes, "is_in_container", lambda pid: False)
    monkeypatch.setattr(routes, "get_cwd", lambda pid: f"{home}/x/app")
    monkeypatch.setattr(routes, "get_cmdline", lambda pid: "node /home/x/app/index.js")
    monkeypatch.setattr(routes, "get_venv", lambda pid: None)
    monkeypatch.setattr(routes, "get_project_name", lambda cwd, t: "app")

    procs = {p["pid"]: p for p in client.get("/api/ps").get_json()}
    assert 4242 in procs
    assert procs[4242]["type"] == "node"
    assert procs[4242]["ports"] == [3000]
    assert 4242 in routes.known_pids   # allowlist populated for a subsequent kill
    # Per-process metrics: RAM from the ps columns; CPU 0.0 on a single scan (no baseline).
    assert procs[4242]["mem_pct"] == 0.2      # %MEM column from ps_out
    assert procs[4242]["cpu"] == 0.0
    assert "mem_mb" in procs[4242]

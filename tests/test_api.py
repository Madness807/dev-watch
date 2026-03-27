"""API tests for dev-watch server."""

import pytest
from src.server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


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
    required = {"pid", "type", "project", "cmd", "ports", "dir"}
    for proc in data:
        assert required.issubset(proc.keys()), f"Missing fields in {proc}"
        assert proc["type"] in ("node", "python")
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

"""Hermetic unit tests for src/helpers.py (no live ps/ss/docker/proc)."""

import builtins
import os
from unittest.mock import mock_open

import pytest

from src import helpers
from src.helpers import (
    classify_process, parse_listening_ports, ports_by_pid, first_pid_and_name,
    get_project_name, get_venv, is_native_binary, get_cpu_usage,
    get_ram_usage, get_disk_usage,
    find_project_root, normalize_name, build_projects,
)


# ── classify_process ──

@pytest.mark.parametrize("cmd,expected", [
    ("node /home/x/app.js", "node"),
    ("npm run dev", "node"),
    ("/home/x/node_modules/.bin/vite", "node"),
    ("python3 manage.py runserver", "python"),
    ("python3.12 -m flask run", "python"),      # versioned interpreter (M1 regression guard)
    ("python3.11 app.py", "python"),
    ("/home/x/.venv/bin/python3 -m uvicorn", "python"),
    ("python /usr/lib/dev-watch/src/server.py", None),  # server.py is excluded
    ("cargo run", "rust"),
    ("/home/x/target/release/app", "rust"),
    ("go run main.go", "go"),
    ("go version", None),                        # bare `go` is not a dev process
    ("deno run mod.ts", "deno"),
    ("bun run index.ts", "bun"),
    ("java -jar app.jar", "java"),
    ("mvn spring-boot:run", "java"),
    ("php artisan serve", "php"),
    ("ruby script.rb", "ruby"),
    ("rails server", "ruby"),
    ("make -j4", "c"),
    ("gcc -o app app.c", "c"),
    ("bash deploy.sh", None),
    ("some-random-binary --flag", None),
])
def test_classify_process(cmd, expected):
    assert classify_process(cmd) == expected


# ── Listening-port parsing ──

SS_TLNP = (
    "State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
    'LISTEN 0 511 0.0.0.0:8080 0.0.0.0:* users:(("nginx",pid=10,fd=6))\n'
    'LISTEN 0 128 192.168.1.5:3000 0.0.0.0:* users:(("node",pid=30,fd=7))\n'
    'LISTEN 0 128 [::1]:631 [::]:* users:(("cupsd",pid=40,fd=8))\n'
    'LISTEN 0 128 127.0.0.1:5432 0.0.0.0:* users:(("pg",pid=20,fd=5),("pg",pid=21,fd=6))\n'
)


def test_parse_listening_ports_binds_and_multipid():
    recs = {r["port"]: r for r in parse_listening_ports(SS_TLNP)}
    assert recs[8080]["bind"] == "all"
    assert recs[3000]["bind"] == "all"      # specific routable IP -> flagged exposed (was dropped before)
    assert recs[631]["bind"] == "local"     # [::1] loopback
    assert recs[5432]["bind"] == "local"    # 127.0.0.1 loopback
    assert recs[8080]["process"] == "nginx"
    assert recs[5432]["pids"] == [20, 21]   # all pids on a shared socket


def test_ports_by_pid():
    m = ports_by_pid(parse_listening_ports(SS_TLNP))
    assert m[10] == [8080]
    assert m[20] == [5432]
    assert m[21] == [5432]
    assert m[30] == [3000]


def test_first_pid_and_name():
    line = 'ESTAB 0 0 127.0.0.1:5432 127.0.0.1:5 users:(("postgres",pid=20,fd=9))'
    assert first_pid_and_name(line) == (20, "postgres")
    assert first_pid_and_name("no process info here") == (None, "")


# ── Project name ──

def test_get_project_name_node_reads_package_json(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "my-app"}')
    assert get_project_name(str(tmp_path), "node") == "my-app"


def test_get_project_name_python_uses_dirname(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool]\n")
    assert get_project_name(str(tmp_path), "python") == tmp_path.name


def test_get_project_name_fallback_and_unknown_cwd(tmp_path):
    assert get_project_name(str(tmp_path), "native") == tmp_path.name
    assert get_project_name("?", "native") == "?"


# ── venv detection ──

def test_get_venv_detected(monkeypatch):
    argv = b"/home/u/proj/.venv/bin/python3\x00-m\x00app\x00"
    monkeypatch.setattr(builtins, "open", mock_open(read_data=argv))
    assert get_venv(1234) == "proj"


def test_get_venv_none_for_system_interpreter(monkeypatch):
    argv = b"/usr/bin/node\x00app.js\x00"
    monkeypatch.setattr(builtins, "open", mock_open(read_data=argv))
    assert get_venv(1234) is None


# ── Native ELF detection ──

def test_is_native_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers.os.path, "expanduser",
                        lambda p: str(tmp_path) if p == "~" else p)
    elf = tmp_path / "app"
    elf.write_bytes(b"\x7fELF" + b"\x00" * 64)
    txt = tmp_path / "script.sh"
    txt.write_bytes(b"#!/bin/sh\necho hi\n")

    monkeypatch.setattr(helpers.os, "readlink", lambda p: str(elf))
    assert is_native_binary(111) is True

    monkeypatch.setattr(helpers.os, "readlink", lambda p: str(txt))
    assert is_native_binary(111) is False              # not ELF

    monkeypatch.setattr(helpers.os, "readlink", lambda p: "/usr/bin/ls")
    assert is_native_binary(111) is False              # outside $HOME


# ── CPU metric math ──

def test_get_cpu_usage_math(monkeypatch):
    # total = 100+0+100+700 = 900, idle = field[4] = 700
    monkeypatch.setattr(builtins, "open", mock_open(read_data="cpu  100 0 100 700 0 0 0 0 0 0\n"))
    pct, state = get_cpu_usage(None)
    assert pct == 0.0 and state == (900, 700)          # first call primes state
    # prev (800, 650): dt=100, di=50 -> busy 50%
    pct2, _ = get_cpu_usage((800, 650))
    assert pct2 == 50.0


def test_usage_fallbacks_are_independent_copies():
    # The shared _EMPTY_USAGE must be returned as a copy, not the singleton.
    r, d = get_ram_usage(), get_disk_usage()
    assert set(r) == {"used", "total", "pct"}
    assert set(d) == {"used", "total", "pct"}


# ── Per-process CPU ──

def test_proc_cpu_percents_first_sample_is_zero():
    # No baseline yet -> every pid reports 0.0
    assert helpers.proc_cpu_percents({10: 500, 20: 900}, 100.0, {}, None) == {10: 0.0, 20: 0.0}


def test_proc_cpu_percents_delta():
    # pid 10 burned 2 core-seconds over 2s -> 100%/core; pid 20 stayed idle -> 0%
    prev = {10: 1000, 20: 5000}
    now_ticks = {10: 1000 + 2 * helpers.CLK_TCK, 20: 5000}
    pct = helpers.proc_cpu_percents(now_ticks, 1002.0, prev, 1000.0)
    assert pct[10] == 100.0
    assert pct[20] == 0.0


def test_proc_cpu_percents_new_pid_is_zero():
    # A pid with no previous sample can't have a delta yet.
    pct = helpers.proc_cpu_percents({30: 400}, 1002.0, {10: 100}, 1000.0)
    assert pct[30] == 0.0


def test_read_proc_ticks_handles_parens_in_comm(monkeypatch):
    # comm contains a space and a ')' — parsing must key off the LAST ')'.
    fields_after = "S " + " ".join(str(i) for i in range(1, 40))
    stat = "4242 (weird )proc) " + fields_after
    monkeypatch.setattr(builtins, "open", mock_open(read_data=stat))
    # fields = ['S','1','2',...] -> utime idx11='11', stime idx12='12' -> 23
    assert helpers.read_proc_ticks(4242) == 23


# ── Project correlation (cockpit) ──

def test_find_project_root_deepest_marker_wins(tmp_path):
    home = tmp_path
    proj = tmp_path / "code" / "myapp"
    sub = proj / "src" / "deep"
    sub.mkdir(parents=True)
    (proj / "package.json").write_text("{}")
    assert find_project_root(str(sub), str(home)) == os.path.realpath(str(proj))


def test_find_project_root_inner_marker_beats_git_root(tmp_path):
    # Fine granularity: an inner package.json splits a monorepo at the app boundary.
    home = tmp_path
    repo = tmp_path / "monorepo"
    (repo / ".git").mkdir(parents=True)
    web = repo / "apps" / "web"
    web.mkdir(parents=True)
    (web / "package.json").write_text("{}")
    assert find_project_root(str(web), str(home)) == os.path.realpath(str(web))


def test_find_project_root_none_for_home_or_unmarked(tmp_path):
    home = tmp_path
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    assert find_project_root(str(scratch), str(home)) is None   # no marker below home
    assert find_project_root(str(home), str(home)) is None      # home itself
    assert find_project_root("?", str(home)) is None


def test_normalize_name():
    assert normalize_name("My-App") == "myapp"
    assert normalize_name("@acme/web") == "web"          # scope segment dropped
    assert normalize_name("C:\\Users\\me\\proj") == "proj"  # backslash path
    assert normalize_name("") == ""


def test_build_projects_process_joins_its_container():
    home = "/home/dev"
    procs = [{"pid": 100, "type": "node", "project": "web", "dir_full": "/home/dev/shop/web",
              "project_root": "/home/dev/shop/web", "cpu": 12.0, "mem_mb": 120}]
    conts = [{"id": "aaa", "name": "db", "image": "postgres", "status": "Up", "health": "healthy",
              "project": "shop", "service": "db", "work_dir": "/home/dev/shop",
              "ports": [{"host": 5432, "container": 5432}]}]
    ports = [{"port": 3000, "pid": 100, "process": "node", "bind": "local"},
             {"port": 5432, "pid": 999, "process": "proxy", "bind": "all"}]
    res = build_projects(procs, conts, ports, home)
    assert [g["key"] for g in res] == ["compose:shop"]
    card = res[0]
    assert len(card["processes"]) == 1 and len(card["containers"]) == 1
    assert {p["port"] for p in card["ports"]} == {3000, 5432}   # pid-join + host-port-join


def test_build_projects_separates_compose_envs():
    home = "/home/dev"
    conts = [{"id": "b", "name": "s1", "image": "redis", "status": "Up", "health": "none",
              "project": "svc-staging", "service": "c", "work_dir": "/home/dev/svc", "ports": []},
             {"id": "c", "name": "s2", "image": "redis", "status": "Up", "health": "none",
              "project": "svc-prod", "service": "c", "work_dir": "/home/dev/svc", "ports": []}]
    res = build_projects([], conts, [], home)
    assert sorted(g["key"] for g in res) == ["compose:svc-prod", "compose:svc-staging"]


def test_build_projects_ungrouped_bucket():
    home = "/home/dev"
    procs = [{"pid": 300, "type": "node", "project": "dev", "dir_full": "/home/dev",
              "project_root": None, "cpu": 0.0, "mem_mb": 10}]
    conts = [{"id": "d", "name": "adhoc", "image": "nginx", "status": "Up", "health": "none",
              "project": "", "service": "", "work_dir": None, "ports": [{"host": 8080, "container": 80}]}]
    ports = [{"port": 9999, "pid": None, "process": "", "bind": "all"}]
    res = build_projects(procs, conts, ports, home)
    assert [g["key"] for g in res] == ["__ungrouped__"]
    u = res[0]
    assert len(u["processes"]) == 1 and len(u["containers"]) == 1
    assert {p["port"] for p in u["ports"]} == {9999}   # orphan port


def test_build_projects_wsl_workdir_bridges_by_name():
    # Compose container whose work_dir is unusable (WSL -> None) merges into the
    # process's dir group when the normalized names match (last-resort bridge).
    home = "/home/dev"
    procs = [{"pid": 1, "type": "node", "project": "myapp", "dir_full": "/home/dev/myapp",
              "project_root": "/home/dev/myapp", "cpu": 1.0, "mem_mb": 5}]
    conts = [{"id": "e", "name": "db", "image": "pg", "status": "Up", "health": "none",
              "project": "myapp", "service": "db", "work_dir": None, "ports": []}]
    res = build_projects(procs, conts, [], home)
    assert len(res) == 1
    assert len(res[0]["processes"]) == 1 and len(res[0]["containers"]) == 1


# ── Audit v1.6.2: get_gpu_usage coverage (F10) ──

def test_get_gpu_usage_parses_nvidia_smi(monkeypatch):
    monkeypatch.setattr(helpers, "run_cmd", lambda cmd: "42, 2048, 8192\n")
    assert helpers.get_gpu_usage() == {"pct": 42.0, "vram_used": 2048, "vram_total": 8192}


def test_get_gpu_usage_first_gpu_only(monkeypatch):
    monkeypatch.setattr(helpers, "run_cmd", lambda cmd: "10, 100, 200\n90, 300, 400\n")
    assert helpers.get_gpu_usage()["pct"] == 10.0


def test_get_gpu_usage_none_without_gpu(monkeypatch):
    monkeypatch.setattr(helpers, "run_cmd", lambda cmd: "")
    assert helpers.get_gpu_usage() is None


def test_get_gpu_usage_none_on_garbage(monkeypatch):
    monkeypatch.setattr(helpers, "run_cmd", lambda cmd: "not,parseable\n")
    assert helpers.get_gpu_usage() is None


# ── Audit v1.6.2: run_cmd_result surfaces returncode + stderr (F6) ──

def test_run_cmd_result_success():
    rc, out, err = helpers.run_cmd_result(["true"])
    assert rc == 0 and err == ""


def test_run_cmd_result_captures_stderr_and_rc():
    rc, out, err = helpers.run_cmd_result(["sh", "-c", "echo oops >&2; exit 3"])
    assert rc == 3 and "oops" in err


def test_run_cmd_result_missing_binary():
    rc, out, err = helpers.run_cmd_result(["definitely-not-a-real-binary-xyz"])
    assert rc != 0 and err

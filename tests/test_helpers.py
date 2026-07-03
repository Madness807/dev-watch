"""Hermetic unit tests for src/helpers.py (no live ps/ss/docker/proc)."""

import builtins
from unittest.mock import mock_open

import pytest

from src import helpers
from src.helpers import (
    classify_process, parse_listening_ports, ports_by_pid, first_pid_and_name,
    get_project_name, get_venv, is_native_binary, get_cpu_usage,
    get_ram_usage, get_disk_usage,
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

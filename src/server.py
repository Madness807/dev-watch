#!/usr/bin/env python3
"""
dev-watch — Local process & container monitor.
Launch: python3 -m src.server
Dashboard: http://localhost:3999
"""

import os
import signal
import sys
import logging
from flask import Flask, request, send_from_directory
from src.config import HOST, PORT
from src.routes import register_routes

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# No CORS: the dashboard is served by this same Flask app (same origin), so no
# cross-origin access is ever needed. Adding a permissive/misconfigured CORS
# policy would only widen the attack surface of an auth-less local API.
app = Flask(__name__)

# Hostnames the browser may legitimately use to reach a loopback-bound server.
_ALLOWED_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}


def _request_hostname():
    """Hostname portion of the Host header, without port or IPv6 brackets."""
    host = request.host or ""
    if host.startswith("["):            # IPv6 literal, e.g. [::1]:3999
        return host[1:host.find("]")] if "]" in host else host[1:]
    return host.rsplit(":", 1)[0] if ":" in host else host


@app.before_request
def _guard_host():
    # Reject requests whose Host is not a loopback name. This closes the
    # DNS-rebinding hole: an attacker page that rebinds its domain to 127.0.0.1
    # still sends its own hostname as Host, so it never reaches the API — the
    # scan-populated allowlists are no longer the only line of defense.
    if _request_hostname() not in _ALLOWED_HOSTNAMES:
        return "Forbidden: invalid Host header", 403


@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


@app.route("/")
def serve_dashboard():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/styles.css")
def serve_css():
    return send_from_directory(STATIC_DIR, "styles.css")


@app.route("/app.js")
def serve_js():
    return send_from_directory(STATIC_DIR, "app.js")


@app.route("/icons/<path:filename>")
def serve_icon(filename):
    return send_from_directory(os.path.join(STATIC_DIR, "icons"), filename)


register_routes(app)


def _graceful_exit(signum, frame):
    """Exit cleanly on SIGTERM so `systemctl stop` shuts the server down."""
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _graceful_exit)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    print(f"\n  dev-watch at http://localhost:{PORT}")
    print("  Ctrl+C to stop\n")
    app.run(host=HOST, port=PORT, debug=False)

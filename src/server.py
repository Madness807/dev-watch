#!/usr/bin/env python3
"""
dev-watch — Local process & container monitor.
Launch: python3 -m src.server
Dashboard: http://localhost:3999
"""

import os
import logging
from flask import Flask, send_from_directory
from flask_cors import CORS
from src.routes import register_routes

PORT = 3999
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__)
CORS(app, origins=["http://localhost:*", "http://127.0.0.1:*"])


@app.route("/")
def serve_dashboard():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/icons/<path:filename>")
def serve_icon(filename):
    return send_from_directory(os.path.join(STATIC_DIR, "icons"), filename)


register_routes(app)


if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    print(f"\n  dev-watch at http://localhost:{PORT}")
    print(f"  Ctrl+C to stop\n")
    app.run(host="127.0.0.1", port=PORT, debug=False)

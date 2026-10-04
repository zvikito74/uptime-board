"""Uptime Board API.

Checks a list of websites on a schedule, stores every result in SQLite and
serves the current status and recent history as JSON.
"""

import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request

HISTORY_LENGTH = 30
KEEP_DAYS = 7

SCHEMA = """
CREATE TABLE IF NOT EXISTS targets (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,
    url     TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS checks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id   INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    checked_at  TEXT NOT NULL,
    ok          INTEGER NOT NULL,
    status_code INTEGER,
    response_ms INTEGER,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_checks_target ON checks(target_id, id);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path, seed=""):
    """Create the tables and, if there are no targets yet, add the seed ones.

    Seed format: "Name|https://example.com,Other|https://example.org"
    """
    folder = os.path.dirname(db_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        if seed and conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0] == 0:
            for item in seed.split(","):
                name, _, url = item.partition("|")
                if name.strip() and url.strip():
                    conn.execute("INSERT OR IGNORE INTO targets (name, url) VALUES (?, ?)",
                                 (name.strip(), url.strip()))


def check_url(url, timeout=5):
    """Request the URL once and report whether it answered successfully."""
    started = time.monotonic()
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "uptime-board/1.0"})
        elapsed = int((time.monotonic() - started) * 1000)
        return {"ok": response.status_code < 400, "status_code": response.status_code,
                "response_ms": elapsed, "error": None}
    except requests.RequestException as error:
        elapsed = int((time.monotonic() - started) * 1000)
        return {"ok": False, "status_code": None, "response_ms": elapsed,
                "error": type(error).__name__}


def run_checks(db_path, checker=check_url):
    """Check every target once and store the results. Returns how many were checked."""
    with connect(db_path) as conn:
        targets = conn.execute("SELECT id, url FROM targets").fetchall()

    results = [(target["id"], checker(target["url"])) for target in targets]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    with connect(db_path) as conn:
        for target_id, result in results:
            conn.execute(
                "INSERT INTO checks (target_id, checked_at, ok, status_code, response_ms, error) "
                "SELECT ?, ?, ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM targets WHERE id = ?)",
                (target_id, now_iso(), int(result["ok"]), result["status_code"],
                 result["response_ms"], result["error"], target_id),
            )
        conn.execute("DELETE FROM checks WHERE checked_at < ?", (cutoff,))
    return len(results)


def checker_loop(db_path, interval, checker, stop_event):
    while not stop_event.is_set():
        try:
            run_checks(db_path, checker)
        except Exception as error:  # keep the loop alive whatever happens
            print(f"check run failed: {error}", flush=True)
        stop_event.wait(interval)


def target_status(conn, target):
    """Build the status summary for one target."""
    history = conn.execute(
        "SELECT checked_at, ok, status_code, response_ms, error FROM checks "
        "WHERE target_id = ? ORDER BY id DESC LIMIT ?",
        (target["id"], HISTORY_LENGTH),
    ).fetchall()

    day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    totals = conn.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(ok), 0) AS up, AVG(response_ms) AS avg_ms "
        "FROM checks WHERE target_id = ? AND checked_at >= ?",
        (target["id"], day_ago),
    ).fetchone()

    last = history[0] if history else None
    return {
        "id": target["id"],
        "name": target["name"],
        "url": target["url"],
        "status": "unknown" if last is None else ("up" if last["ok"] else "down"),
        "last_checked": last["checked_at"] if last else None,
        "last_status_code": last["status_code"] if last else None,
        "last_response_ms": last["response_ms"] if last else None,
        "last_error": last["error"] if last else None,
        "uptime_24h": round(100 * totals["up"] / totals["total"], 2) if totals["total"] else None,
        "avg_response_ms": round(totals["avg_ms"]) if totals["avg_ms"] is not None else None,
        # oldest first, so the frontend can draw it left to right
        "history": [{"at": row["checked_at"], "ok": bool(row["ok"]), "ms": row["response_ms"]}
                    for row in reversed(history)],
    }


def valid_url(url):
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def create_app(db_path=None, start_checker=True, checker=check_url):
    db_path = db_path or os.environ.get("DB_PATH", "data/uptime.db")
    interval = int(os.environ.get("CHECK_INTERVAL", "30"))
    init_db(db_path, os.environ.get("SEED_TARGETS", ""))

    app = Flask(__name__)

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/targets")
    def list_targets():
        with connect(db_path) as conn:
            targets = conn.execute("SELECT * FROM targets ORDER BY name").fetchall()
            return jsonify([target_status(conn, target) for target in targets])

    @app.post("/api/targets")
    def add_target():
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        url = str(data.get("url", "")).strip()
        if not name or len(name) > 60:
            return jsonify(error="name is required (60 characters at most)"), 400
        if not valid_url(url):
            return jsonify(error="url must start with http:// or https://"), 400
        try:
            with connect(db_path) as conn:
                cursor = conn.execute("INSERT INTO targets (name, url) VALUES (?, ?)", (name, url))
                return jsonify(id=cursor.lastrowid, name=name, url=url), 201
        except sqlite3.IntegrityError:
            return jsonify(error="this url is already being monitored"), 409

    @app.delete("/api/targets/<int:target_id>")
    def delete_target(target_id):
        with connect(db_path) as conn:
            deleted = conn.execute("DELETE FROM targets WHERE id = ?", (target_id,)).rowcount
        if not deleted:
            return jsonify(error="target not found"), 404
        return "", 204

    @app.post("/api/check")
    def check_now():
        return jsonify(checked=run_checks(db_path, checker))

    if start_checker:
        stop_event = threading.Event()
        thread = threading.Thread(target=checker_loop, args=(db_path, interval, checker, stop_event),
                                  daemon=True)
        thread.start()

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8000)

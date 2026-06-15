from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from flask import Flask, jsonify, redirect, request, send_from_directory

from importer import BASE_URL, DB_PATH, ensure_db, fetch_lesson_details


ROOT = Path(__file__).parent
app = Flask(__name__, static_folder="static")


def db() -> sqlite3.Connection:
    ensure_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


@app.get("/")
def index():
    return redirect("/static/index.html")


@app.get("/<path:asset>")
def root_static_asset(asset: str):
    allowed = {
        "app.js",
        "styles.css",
        "manifest.webmanifest",
        "icon.svg",
        "icon-192.png",
        "icon-512.png",
        "apple-touch-icon.png",
        "sw.js",
    }
    if asset in allowed or asset.startswith("data/"):
        return send_from_directory(app.static_folder, asset)
    return jsonify({"error": "not found"}), 404


@app.get("/api/stats")
def stats():
    with db() as conn:
        totals = conn.execute(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END) AS done,
              SUM(CASE WHEN completed_at IS NULL THEN 1 ELSE 0 END) AS todo
            FROM lessons
            """
        ).fetchone()
        today = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM lesson_sessions
            WHERE date(created_at) = date('now', 'localtime')
            """
        ).fetchone()
        return jsonify({"totals": row_to_dict(totals), "today": today["count"]})


@app.get("/api/categories")
def categories():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT c.slug, c.name, c.levels, c.description, COUNT(l.id) AS lesson_count,
                   SUM(CASE WHEN l.completed_at IS NOT NULL THEN 1 ELSE 0 END) AS done_count
            FROM categories c
            LEFT JOIN lessons l ON l.category_slug = c.slug
            GROUP BY c.slug
            ORDER BY c.position, c.name
            """
        ).fetchall()
        return jsonify([row_to_dict(row) for row in rows])


@app.get("/api/lessons")
def lessons():
    category = request.args.get("category", "")
    status = request.args.get("status", "todo")
    q = request.args.get("q", "").strip()
    level = request.args.get("level", "")
    params = []
    where = ["1 = 1"]
    if category:
        where.append("l.category_slug = ?")
        params.append(category)
    if status == "todo":
        where.append("l.completed_at IS NULL")
    elif status == "done":
        where.append("l.completed_at IS NOT NULL")
    if q:
        where.append("(l.title LIKE ? OR l.subtitle LIKE ? OR c.name LIKE ?)")
        needle = f"%{q}%"
        params.extend([needle, needle, needle])
    if level:
        where.append("l.level = ?")
        params.append(level)

    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT l.*, c.name AS category_name
            FROM lessons l
            JOIN categories c ON c.slug = l.category_slug
            WHERE {' AND '.join(where)}
            ORDER BY c.position, l.position, l.title
            LIMIT 500
            """,
            params,
        ).fetchall()
        return jsonify([row_to_dict(row) for row in rows])


@app.get("/api/lessons/<int:lesson_id>")
def lesson_detail(lesson_id: int):
    with db() as conn:
        lesson = conn.execute(
            """
            SELECT l.*, c.name AS category_name
            FROM lessons l
            JOIN categories c ON c.slug = l.category_slug
            WHERE l.id = ?
            """,
            (lesson_id,),
        ).fetchone()
        if lesson is None:
            return jsonify({"error": "not found"}), 404

    if not lesson["url"] or lesson["url"].startswith("dd-local://"):
        with db() as conn:
            conn.execute(
                "UPDATE lessons SET details_cached_at = COALESCE(details_cached_at, ?) WHERE id = ?",
                (datetime.now().isoformat(timespec="seconds"), lesson_id),
            )
            conn.commit()
    elif not lesson["details_cached_at"]:
        try:
            fetch_lesson_details(lesson_id)
        except (URLError, TimeoutError, ValueError) as exc:
            return jsonify({"error": f"Detay çekilemedi: {exc}"}), 502

    with db() as conn:
        lesson = conn.execute(
            """
            SELECT l.*, c.name AS category_name
            FROM lessons l
            JOIN categories c ON c.slug = l.category_slug
            WHERE l.id = ?
            """,
            (lesson_id,),
        ).fetchone()
        challenges = conn.execute(
            """
            SELECT *
            FROM challenges
            WHERE lesson_id = ?
            ORDER BY position
            """,
            (lesson_id,),
        ).fetchall()
    data = row_to_dict(lesson)
    data["challenges"] = [row_to_dict(row) for row in challenges]
    return jsonify(data)


@app.post("/api/lessons/<int:lesson_id>/complete")
def complete_lesson(lesson_id: int):
    payload = request.get_json(silent=True) or {}
    seconds = int(payload.get("seconds") or 0)
    notes = str(payload.get("notes") or "").strip()
    now = datetime.now().isoformat(timespec="seconds")
    with db() as conn:
        conn.execute(
            """
            UPDATE lessons
            SET completed_at = COALESCE(completed_at, ?), notes = ?
            WHERE id = ?
            """,
            (now, notes, lesson_id),
        )
        conn.execute(
            """
            INSERT INTO lesson_sessions (lesson_id, created_at, seconds, notes)
            VALUES (?, ?, ?, ?)
            """,
            (lesson_id, now, seconds, notes),
        )
        conn.commit()
    return jsonify({"ok": True, "completed_at": now})


@app.post("/api/lessons/<int:lesson_id>/reset")
def reset_lesson(lesson_id: int):
    with db() as conn:
        conn.execute(
            "UPDATE lessons SET completed_at = NULL, notes = '' WHERE id = ?",
            (lesson_id,),
        )
        conn.commit()
    return jsonify({"ok": True})


@app.get("/api/sessions")
def sessions():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT s.*, l.title, c.name AS category_name
            FROM lesson_sessions s
            JOIN lessons l ON l.id = s.lesson_id
            JOIN categories c ON c.slug = l.category_slug
            ORDER BY s.created_at DESC
            LIMIT 100
            """
        ).fetchall()
        return jsonify([row_to_dict(row) for row in rows])


@app.get("/audio/<int:lesson_id>")
def audio_proxy(lesson_id: int):
    with db() as conn:
        lesson = conn.execute("SELECT audio_url, local_audio_path FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    if lesson is None:
        return jsonify({"error": "not found"}), 404
    if lesson["local_audio_path"]:
        path = ROOT / lesson["local_audio_path"]
        if path.exists():
            return send_from_directory(path.parent, path.name)
    return jsonify({"audio_url": lesson["audio_url"]})


if __name__ == "__main__":
    ensure_db()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5050")), debug=True)

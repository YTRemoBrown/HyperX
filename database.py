# -*- coding: utf-8 -*-
"""
HyperX Database - SQLite History
Developed by: ريمو براون
© 2026 All Rights Reserved
"""
import os
import json
import sqlite3
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "history.db")


def _conn():
    os.makedirs(DB_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                package TEXT,
                app_name TEXT,
                version TEXT,
                sha256 TEXT,
                score INTEGER,
                grade TEXT,
                findings_count INTEGER,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_sha256 ON analyses(sha256)
        """)
        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_created ON analyses(created_at)
        """)
        con.commit()


def save_analysis(data):
    """حفظ تحليل كامل. يرجع id."""
    b = data.get("basic", {})
    sc = data.get("security_score", {})
    st = data.get("stats", {})
    try:
        with _conn() as con:
            cur = con.execute("""
                INSERT INTO analyses
                (filename, package, app_name, version, sha256,
                 score, grade, findings_count, data_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                b.get("name", ""),
                b.get("package", ""),
                b.get("app_name", ""),
                b.get("version", ""),
                b.get("sha256", ""),
                sc.get("score", 0),
                sc.get("grade", ""),
                st.get("total_findings", 0),
                json.dumps(data, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ))
            con.commit()
            return cur.lastrowid
    except Exception as e:
        print("DB save error:", e)
        return None


def list_analyses(limit=100, query=""):
    """قائمة التحليلات بدون JSON الكامل."""
    with _conn() as con:
        if query:
            like = f"%{query}%"
            rows = con.execute("""
                SELECT id, filename, package, app_name, version,
                       sha256, score, grade, findings_count, created_at
                FROM analyses
                WHERE filename LIKE ? OR package LIKE ? OR app_name LIKE ?
                ORDER BY id DESC LIMIT ?
            """, (like, like, like, limit)).fetchall()
        else:
            rows = con.execute("""
                SELECT id, filename, package, app_name, version,
                       sha256, score, grade, findings_count, created_at
                FROM analyses
                ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_analysis(aid):
    with _conn() as con:
        row = con.execute("SELECT * FROM analyses WHERE id=?", (aid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["data"] = json.loads(d["data_json"])
        del d["data_json"]
        return d


def get_latest():
    """آخر تحليل كامل."""
    with _conn() as con:
        row = con.execute(
            "SELECT id, data_json, created_at FROM analyses ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "data": json.loads(row["data_json"]),
        }


def delete_analysis(aid):
    with _conn() as con:
        con.execute("DELETE FROM analyses WHERE id=?", (aid,))
        con.commit()


def clear_all():
    with _conn() as con:
        con.execute("DELETE FROM analyses")
        con.commit()


def stats():
    with _conn() as con:
        total = con.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
        avg = con.execute("SELECT AVG(score) FROM analyses").fetchone()[0] or 0
        best = con.execute("SELECT MAX(score) FROM analyses").fetchone()[0] or 0
        worst = con.execute("SELECT MIN(score) FROM analyses").fetchone()[0] or 0
        return {
            "total": total,
            "avg_score": round(avg, 1),
            "best": best,
            "worst": worst,
        }

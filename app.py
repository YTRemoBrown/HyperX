# -*- coding: utf-8 -*-
"""
HyperX v5.0 - Web Server + SSE Progress
Developed by: ريمو براون
© 2026 All Rights Reserved
"""
import os
import json
import queue
import tempfile
import threading
import uuid
from flask import Flask, render_template, request, jsonify, Response
from hunter_core import analyze_apk
from resource_guard import (
    check_apk_size, check_zip_contents, cleanup_orphans,
    ResourceError, LIMITS, check_memory
)
import database as db

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = LIMITS["max_apk_mb"] * 1024 * 1024
ALLOWED = (".apk", ".apks", ".xapk", ".zip", ".tgz", ".tar.gz")

db.init_db()
cleanup_orphans()

# ═══════════════════════════════════════════════════════════
# Jobs store — لتتبع التقدم عبر SSE
# ═══════════════════════════════════════════════════════════
JOBS = {}          # {job_id: {"q": Queue, "result": None, "done": False}}
JOBS_LOCK = threading.Lock()


def _new_job():
    jid = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[jid] = {
            "q": queue.Queue(),
            "result": None,
            "done": False,
        }
    return jid


def _emit(jid, pct, stage=""):
    with JOBS_LOCK:
        if jid in JOBS:
            try:
                JOBS[jid]["q"].put_nowait({"pct": pct, "stage": stage})
            except Exception:
                pass


def _finish(jid, result):
    with JOBS_LOCK:
        if jid in JOBS:
            JOBS[jid]["result"] = result
            JOBS[jid]["done"] = True
            try:
                JOBS[jid]["q"].put_nowait({"pct": 100, "stage": "done", "done": True})
            except Exception:
                pass


def _worker(jid, tmp_path, original_filename):
    """خيط منفصل يقوم بالتحليل."""
    try:
        def cb(pct, stage=""):
            _emit(jid, pct, stage)

        result = analyze_apk(tmp_path, progress_cb=cb)
        if result.get("ok"):
            result["data"]["basic"]["name"] = original_filename
            aid = db.save_analysis(result["data"])
            result["history_id"] = aid
        _finish(jid, result)
    except ResourceError as e:
        _finish(jid, {"ok": False, "error": str(e)})
    except Exception as e:
        _finish(jid, {"ok": False, "error": f"خطأ غير متوقع: {e}"})
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/history")
def history_page():
    return render_template("history.html")


@app.route("/api/limits", methods=["GET"])
def api_limits():
    try:
        mem_mb = check_memory()
    except Exception:
        mem_mb = 0
    return jsonify({
        "ok": True,
        "limits": LIMITS,
        "current_mem_mb": round(mem_mb, 1),
    })


@app.route("/api/start", methods=["POST"])
def api_start():
    """يستقبل الملف، يبدأ التحليل في خيط منفصل، ويرجع job_id."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "لم يتم إرسال ملف"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "اسم ملف فارغ"}), 400
    low = f.filename.lower()
    if not any(low.endswith(ext) for ext in ALLOWED):
        return jsonify({"ok": False, "error": "الملف يجب أن يكون APK أو ZIP"}), 400

    suffix = "." + low.rsplit(".", 1)[-1] if "." in low else ".bin"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        f.save(tmp.name)
        tmp.close()
        # فحوصات سريعة
        try:
            check_apk_size(tmp.name)
            if tmp.name.lower().endswith((".zip", ".apk", ".apks", ".xapk")):
                check_zip_contents(tmp.name)
        except ResourceError as e:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(e)}), 413

        jid = _new_job()
        t = threading.Thread(
            target=_worker,
            args=(jid, tmp.name, f.filename),
            daemon=True,
        )
        t.start()
        return jsonify({"ok": True, "job_id": jid})
    except Exception as e:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        return jsonify({"ok": False, "error": f"فشل: {e}"}), 500


@app.route("/api/progress/<jid>")
def api_progress(jid):
    """SSE — يبث نسبة التقدم."""
    def gen():
        last = -1
        while True:
            with JOBS_LOCK:
                job = JOBS.get(jid)
            if not job:
                yield f"data: {json.dumps({'error': 'job not found'})}\n\n"
                return
            try:
                item = job["q"].get(timeout=15)
            except queue.Empty:
                # نبضة حياة
                yield f"data: {json.dumps({'pct': last if last >= 0 else 0, 'stage': '...'})}\n\n"
                if job["done"]:
                    break
                continue

            last = item.get("pct", last)
            yield f"data: {json.dumps(item)}\n\n"
            if item.get("done"):
                break

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/result/<jid>")
def api_result(jid):
    with JOBS_LOCK:
        job = JOBS.get(jid)
        if not job:
            return jsonify({"ok": False, "error": "job not found"}), 404
        if not job["done"]:
            return jsonify({"ok": False, "error": "not ready"}), 202
        result = job["result"]
        # نظّف الوظيفة بعد الاستلام
        try:
            del JOBS[jid]
        except Exception:
            pass
    return jsonify(result)


# ═══════════════════════════════════════════════════════════
# History (بدون تغيير)
# ═══════════════════════════════════════════════════════════
@app.route("/api/history", methods=["GET"])
def api_history():
    q = request.args.get("q", "").strip()
    limit = int(request.args.get("limit", 100))
    items = db.list_analyses(limit=limit, query=q)
    return jsonify({"ok": True, "items": items, "stats": db.stats()})


@app.route("/api/history/<int:aid>", methods=["GET"])
def api_history_get(aid):
    item = db.get_analysis(aid)
    if not item:
        return jsonify({"ok": False, "error": "غير موجود"}), 404
    return jsonify({"ok": True, "item": item})


@app.route("/api/history/<int:aid>", methods=["DELETE"])
def api_history_delete(aid):
    db.delete_analysis(aid)
    return jsonify({"ok": True})


@app.route("/api/history/clear", methods=["POST"])
def api_history_clear():
    db.clear_all()
    return jsonify({"ok": True})


@app.route("/api/history/latest", methods=["GET"])
def api_history_latest():
    item = db.get_latest()
    if not item:
        return jsonify({"ok": True, "item": None})
    return jsonify({"ok": True, "item": item})


@app.route("/api/export/<int:aid>.<fmt>", methods=["GET"])
def api_export(aid, fmt):
    item = db.get_analysis(aid)
    if not item:
        return "Not found", 404
    data = item["data"]
    fname_base = f"hyperx_{item.get('package') or aid}"

    if fmt == "json":
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        return Response(
            payload, mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={fname_base}.json"},
        )

    if fmt == "txt":
        lines = []
        lines.append("=" * 60)
        lines.append("   HyperX v5.0 - APK Analysis Report")
        lines.append("   Developed by: ريمو براون  |  © 2026")
        lines.append("=" * 60)
        b = data.get("basic", {})
        lines.append("\n[ BASIC INFO ]")
        for k, v in b.items():
            if k == "permissions":
                lines.append(f"  permissions: ({len(v)})")
                for p in v:
                    lines.append(f"    - {p}")
            else:
                lines.append(f"  {k}: {v}")

        sc = data.get("security_score", {})
        lines.append("\n[ SECURITY SCORE ]")
        lines.append(f"  Score: {sc.get('score')}  Grade: {sc.get('grade')}")
        for i in sc.get("issues", []):
            lines.append(f"  - {i}")

        def sec(title, items, fields):
            lines.append(f"\n[ {title} ]")
            if not items:
                lines.append("  (none)")
                return
            for it in items:
                line = "  "
                for f in fields:
                    line += f"{f}={it.get(f)}  "
                if it.get("context"):
                    line += "  context=" + " | ".join(it["context"])
                lines.append(line)

        sec("DEVELOPERS", data.get("developers", []), ["value", "file"])
        sec("EMAILS", data.get("emails", []), ["value", "file"])
        sec("WEBSITES", data.get("websites", []), ["value", "file"])
        sec("TRACKERS", data.get("trackers", []), ["name", "domain"])
        sec("SECRETS", data.get("secrets", []), ["type", "value", "file"])
        sec("CRYPTO", data.get("crypto", []), ["type", "value"])
        sec("IPS", data.get("ips", []), ["value", "file"])
        sec("SO LIBS", data.get("so_libs", []), ["lib", "size_kb"])
        sec("SO SYMBOLS", data.get("so_symbols", []), ["lib", "symbol"])
        sec("RESOURCES", data.get("resources", []), ["key", "value", "file"])

        lines.append("\n[ SOCIAL ]")
        for k, arr in (data.get("social") or {}).items():
            lines.append(f"  {k}:")
            for it in arr:
                lines.append(f"    - {it.get('value')}  ({it.get('file')})")

        payload = "\n".join(lines)
        return Response(
            payload, mimetype="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={fname_base}.txt"},
        )

    return "Unsupported format", 400


@app.errorhandler(413)
def too_large(e):
    return jsonify({
        "ok": False,
        "error": f"⚠️ الملف أكبر من {LIMITS['max_apk_mb']} MB. اختر ملفاً أصغر."
    }), 413


if __name__ == "__main__":
    print("╔══════════════════════════════════╗")
    print("║     HyperX v5.0  -  Running      ║")
    print("║   Developed by: ريمو براون        ║")
    print("║   © 2026 All Rights Reserved     ║")
    print("╚══════════════════════════════════╝")
    print(f"🛡️  حدود الحماية:")
    print(f"    - APK max: {LIMITS['max_apk_mb']} MB")
    print(f"    - Unpacked max: {LIMITS['max_unpacked_mb']} MB")
    print(f"    - Python RAM max: {LIMITS['max_python_mem_mb']} MB")
    print(f"➡  http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

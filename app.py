"""CloudPrint — server local de printare pentru Raspberry Pi (CUPS).

Aplicație Flask minimală, gândită pentru hardware modest (Pi Zero W):
- fără dependențe grele, doar Flask + utilitarele CUPS din linia de comandă
- randarea PDF pentru previzualizare se face în browser (PDF.js),
  serverul doar servește fișierele
- fișierele încărcate și istoricul printărilor sunt păstrate într-o
  bază SQLite (din biblioteca standard), ca să poți reprinta oricând
"""

import json
import os
import re
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DB_PATH = BASE_DIR / "cloudprint.db"

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".txt"}
MAX_UPLOAD_MB = 50

PAGE_RANGE_RE = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")
FILE_ID_RE = re.compile(r"^[0-9a-f]{32}\.[a-z]+$")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+-\d+$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


# ------------------------------------------------------------------ bază de date

def get_db():
    """Conexiune SQLite per-request (Flask rulează multi-thread)."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS files (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            type            TEXT NOT NULL,
            size            INTEGER NOT NULL,
            created_at      REAL NOT NULL,
            last_printed_at REAL,
            print_count     INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id    TEXT,
            name       TEXT NOT NULL,
            type       TEXT NOT NULL,
            printer    TEXT,
            job_id     TEXT,
            options    TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


init_db()


# ------------------------------------------------------------------ utilitare

def run_command(args, timeout=15):
    """Rulează o comandă CUPS și întoarce (ok, stdout, stderr)."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "", f"comanda '{args[0]}' nu există (CUPS nu este instalat?)"
    except subprocess.TimeoutExpired:
        return False, "", f"comanda '{args[0]}' a expirat"
    return result.returncode == 0, result.stdout, result.stderr


def file_row(file_id):
    return get_db().execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()


# ------------------------------------------------------------------ pagini

@app.route("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------------ imprimante

@app.route("/api/printers")
def list_printers():
    ok, out, err = run_command(["lpstat", "-p"])
    if not ok and not out:
        return jsonify({"printers": [], "default": None, "error": err.strip()})

    printers = []
    for line in out.splitlines():
        match = re.match(r"^printer (\S+) (.*)$", line.strip())
        if not match:
            continue
        name, rest = match.group(1), match.group(2).lower()
        if "printing" in rest:
            state = "printing"
        elif "disabled" in rest:
            state = "disabled"
        else:
            state = "idle"
        printers.append({"name": name, "state": state})

    default = None
    ok, out, _ = run_command(["lpstat", "-d"])
    if ok:
        match = re.search(r":\s*(\S+)\s*$", out)
        if match:
            default = match.group(1)
    if default is None and printers:
        default = printers[0]["name"]

    return jsonify({"printers": printers, "default": default, "error": None})


# ------------------------------------------------------------------ fișiere

@app.route("/api/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "Niciun fișier trimis."}), 400

    ext = Path(file.filename).suffix.lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in ALLOWED_EXTENSIONS:
        return (
            jsonify(
                {"error": "Format neacceptat. Formate permise: PDF, JPG, PNG, GIF, TXT."}
            ),
            400,
        )

    file_id = uuid.uuid4().hex + ext
    dest = UPLOAD_DIR / file_id
    file.save(dest)
    size = dest.stat().st_size

    db = get_db()
    db.execute(
        "INSERT INTO files (id, name, type, size, created_at) VALUES (?, ?, ?, ?, ?)",
        (file_id, file.filename, ext.lstrip("."), size, time.time()),
    )
    db.commit()

    return jsonify(
        {
            "id": file_id,
            "name": file.filename,
            "type": ext.lstrip("."),
            "size": size,
            "url": f"/files/{file_id}",
        }
    )


@app.route("/api/files")
def list_files():
    rows = get_db().execute(
        "SELECT * FROM files ORDER BY created_at DESC"
    ).fetchall()
    files = [
        {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "size": r["size"],
            "url": f"/files/{r['id']}",
            "created_at": r["created_at"],
            "last_printed_at": r["last_printed_at"],
            "print_count": r["print_count"],
        }
        for r in rows
    ]
    return jsonify({"files": files})


@app.route("/api/files/<file_id>", methods=["DELETE"])
def delete_file(file_id):
    if not FILE_ID_RE.match(file_id):
        return jsonify({"error": "Id invalid."}), 400
    db = get_db()
    db.execute("DELETE FROM files WHERE id = ?", (file_id,))
    db.commit()
    try:
        (UPLOAD_DIR / file_id).unlink()
    except OSError:
        pass
    return jsonify({"ok": True})


@app.route("/files/<file_id>")
def serve_file(file_id):
    if not FILE_ID_RE.match(file_id):
        abort(404)
    return send_from_directory(UPLOAD_DIR, file_id)


# ------------------------------------------------------------------ printare

@app.route("/api/print", methods=["POST"])
def print_file():
    data = request.get_json(silent=True) or {}

    file_id = data.get("file_id", "")
    if not FILE_ID_RE.match(file_id) or not (UPLOAD_DIR / file_id).exists():
        return jsonify({"error": "Fișierul nu a fost găsit. Încarcă-l din nou."}), 400

    row = file_row(file_id)

    args = ["lp"]

    printer = data.get("printer")
    if printer:
        if not re.match(r"^[A-Za-z0-9_.-]+$", printer):
            return jsonify({"error": "Nume de imprimantă invalid."}), 400
        args += ["-d", printer]

    try:
        copies = int(data.get("copies", 1))
    except (TypeError, ValueError):
        copies = 1
    copies = max(1, min(copies, 99))
    args += ["-n", str(copies)]

    title = row["name"] if row else file_id
    args += ["-t", title[:120]]

    grayscale = bool(data.get("grayscale"))
    duplex = bool(data.get("duplex"))
    duplex_edge = "short" if data.get("duplex_edge") == "short" else "long"

    if duplex:
        args += ["-o", f"sides=two-sided-{duplex_edge}-edge"]
    else:
        args += ["-o", "sides=one-sided"]

    if grayscale:
        args += ["-o", "print-color-mode=monochrome", "-o", "ColorModel=Gray"]

    page_range = (data.get("page_range") or "").replace(" ", "")
    if page_range:
        if not PAGE_RANGE_RE.match(page_range):
            return jsonify({"error": "Interval de pagini invalid. Exemplu: 1-3,5,8"}), 400
        args += ["-o", f"page-ranges={page_range}"]

    media = data.get("media")
    if media in {"A4", "A5", "Letter", "Legal"}:
        args += ["-o", f"media={media}"]

    landscape = bool(data.get("landscape"))
    if landscape:
        args += ["-o", "landscape"]

    quality = data.get("quality")
    if quality in {"draft", "normal", "high"}:
        level = {"draft": "3", "normal": "4", "high": "5"}[quality]
        args += ["-o", f"print-quality={level}"]

    fit_to_page = bool(data.get("fit_to_page"))
    if fit_to_page:
        args += ["-o", "fit-to-page"]

    args.append(str(UPLOAD_DIR / file_id))

    ok, out, err = run_command(args, timeout=30)
    if not ok:
        return jsonify({"error": err.strip() or "Comanda lp a eșuat."}), 502

    job_id = None
    match = re.search(r"request id is (\S+)", out)
    if match:
        job_id = match.group(1)

    # opțiunile efectiv folosite — pentru reprintare identică din istoric
    options = {
        "printer": printer,
        "copies": copies,
        "grayscale": grayscale,
        "duplex": duplex,
        "duplex_edge": duplex_edge,
        "landscape": landscape,
        "media": media if media in {"A4", "A5", "Letter", "Legal"} else "A4",
        "quality": quality if quality in {"draft", "normal", "high"} else "normal",
        "page_range": page_range,
        "fit_to_page": fit_to_page,
    }

    db = get_db()
    now = time.time()
    if row:
        db.execute(
            "UPDATE files SET last_printed_at = ?, print_count = print_count + 1 "
            "WHERE id = ?",
            (now, file_id),
        )
    db.execute(
        "INSERT INTO history (file_id, name, type, printer, job_id, options, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            file_id,
            title,
            row["type"] if row else "",
            printer,
            job_id,
            json.dumps(options),
            now,
        ),
    )
    db.commit()

    return jsonify({"job_id": job_id, "title": title, "copies": copies})


# ------------------------------------------------------------------ istoric

@app.route("/api/history")
def list_history():
    rows = get_db().execute(
        "SELECT * FROM history ORDER BY created_at DESC LIMIT 100"
    ).fetchall()
    items = []
    for r in rows:
        file_exists = bool(r["file_id"]) and (UPLOAD_DIR / r["file_id"]).exists()
        items.append(
            {
                "id": r["id"],
                "file_id": r["file_id"],
                "name": r["name"],
                "type": r["type"],
                "printer": r["printer"],
                "options": json.loads(r["options"]),
                "created_at": r["created_at"],
                "can_reprint": file_exists,
            }
        )
    return jsonify({"history": items})


@app.route("/api/history", methods=["DELETE"])
def clear_history():
    db = get_db()
    db.execute("DELETE FROM history")
    db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ coadă CUPS (live)

@app.route("/api/jobs")
def list_jobs():
    ok, out, err = run_command(["lpstat", "-o"])
    if not ok and err:
        return jsonify({"jobs": [], "error": err.strip()})

    # titluri din istoric, ca să afișăm numele fișierului în coadă
    titles = {
        r["job_id"]: r["name"]
        for r in get_db().execute(
            "SELECT job_id, name FROM history WHERE job_id IS NOT NULL"
        ).fetchall()
    }

    jobs = []
    for line in out.splitlines():
        parts = line.split()
        if not parts or "-" not in parts[0]:
            continue
        job_id = parts[0]
        printer, _, number = job_id.rpartition("-")
        jobs.append(
            {
                "id": job_id,
                "printer": printer,
                "number": number,
                "title": titles.get(job_id),
                "size": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None,
            }
        )

    return jsonify({"jobs": jobs, "error": None})


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    if not JOB_ID_RE.match(job_id):
        return jsonify({"error": "Id de job invalid."}), 400
    ok, _, err = run_command(["cancel", job_id])
    if not ok:
        return jsonify({"error": err.strip() or "Anularea a eșuat."}), 502
    return jsonify({"ok": True})


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": f"Fișier prea mare. Limita este {MAX_UPLOAD_MB} MB."}), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True)

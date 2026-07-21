"""CloudPrint — server local de printare pentru Raspberry Pi (CUPS).

Aplicație Flask minimală, gândită pentru hardware modest (Pi Zero W):
- fără dependențe grele, doar Flask + utilitarele CUPS din linia de comandă
- randarea PDF pentru previzualizare se face în browser (PDF.js),
  serverul doar servește fișierele
"""

import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".txt"}
MAX_UPLOAD_MB = 50
UPLOAD_TTL_SECONDS = 24 * 60 * 60  # fișierele mai vechi de o zi se șterg

PAGE_RANGE_RE = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")
FILE_ID_RE = re.compile(r"^[0-9a-f]{32}\.[a-z]+$")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+-\d+$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# nume original al fișierului, per id (doar informativ, pentru titlul jobului)
_original_names = {}


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


def cleanup_old_uploads():
    now = time.time()
    for path in UPLOAD_DIR.iterdir():
        try:
            if now - path.stat().st_mtime > UPLOAD_TTL_SECONDS:
                path.unlink()
                _original_names.pop(path.name, None)
        except OSError:
            pass


@app.route("/")
def index():
    return render_template("index.html")


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


@app.route("/api/upload", methods=["POST"])
def upload():
    cleanup_old_uploads()

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "Niciun fișier trimis."}), 400

    ext = Path(file.filename).suffix.lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in ALLOWED_EXTENSIONS:
        return (
            jsonify(
                {
                    "error": "Format neacceptat. Formate permise: PDF, JPG, PNG, GIF, TXT."
                }
            ),
            400,
        )

    file_id = uuid.uuid4().hex + ext
    file.save(UPLOAD_DIR / file_id)
    _original_names[file_id] = file.filename

    return jsonify(
        {
            "id": file_id,
            "name": file.filename,
            "type": ext.lstrip("."),
            "size": (UPLOAD_DIR / file_id).stat().st_size,
            "url": f"/files/{file_id}",
        }
    )


@app.route("/files/<file_id>")
def serve_file(file_id):
    if not FILE_ID_RE.match(file_id):
        abort(404)
    return send_from_directory(UPLOAD_DIR, file_id)


@app.route("/api/print", methods=["POST"])
def print_file():
    data = request.get_json(silent=True) or {}

    file_id = data.get("file_id", "")
    if not FILE_ID_RE.match(file_id) or not (UPLOAD_DIR / file_id).exists():
        return jsonify({"error": "Fișierul nu a fost găsit. Încarcă-l din nou."}), 400

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

    title = _original_names.get(file_id, file_id)
    args += ["-t", title[:120]]

    if data.get("duplex"):
        edge = "short" if data.get("duplex_edge") == "short" else "long"
        args += ["-o", f"sides=two-sided-{edge}-edge"]
    else:
        args += ["-o", "sides=one-sided"]

    if data.get("grayscale"):
        # ambele variante, pentru compatibilitate cu drivere diferite
        args += ["-o", "print-color-mode=monochrome", "-o", "ColorModel=Gray"]

    page_range = (data.get("page_range") or "").replace(" ", "")
    if page_range:
        if not PAGE_RANGE_RE.match(page_range):
            return (
                jsonify({"error": "Interval de pagini invalid. Exemplu: 1-3,5,8"}),
                400,
            )
        args += ["-o", f"page-ranges={page_range}"]

    media = data.get("media")
    if media in {"A4", "A5", "Letter", "Legal"}:
        args += ["-o", f"media={media}"]

    if data.get("landscape"):
        args += ["-o", "landscape"]

    quality = data.get("quality")
    if quality in {"draft", "normal", "high"}:
        level = {"draft": "3", "normal": "4", "high": "5"}[quality]
        args += ["-o", f"print-quality={level}"]

    if data.get("fit_to_page"):
        args += ["-o", "fit-to-page"]

    args.append(str(UPLOAD_DIR / file_id))

    ok, out, err = run_command(args, timeout=30)
    if not ok:
        return jsonify({"error": err.strip() or "Comanda lp a eșuat."}), 502

    job_id = None
    match = re.search(r"request id is (\S+)", out)
    if match:
        job_id = match.group(1)

    return jsonify({"job_id": job_id, "title": title, "copies": copies})


@app.route("/api/jobs")
def list_jobs():
    ok, out, err = run_command(["lpstat", "-o"])
    if not ok and err:
        return jsonify({"jobs": [], "error": err.strip()})

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
    return (
        jsonify({"error": f"Fișier prea mare. Limita este {MAX_UPLOAD_MB} MB."}),
        413,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True)

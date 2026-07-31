"""CloudPrint — printare la distanță pentru Raspberry Pi (CUPS).

Aplicație Flask minimală, gândită pentru hardware modest (Pi Zero W). Poate
rula în trei moduri (variabila de mediu CLOUDPRINT_MODE):

- ``local``  (implicit) — totul pe Pi, în rețeaua locală: interfața web +
  printarea directă prin CUPS. Așa a funcționat dintotdeauna.

- ``cloud``  — aceeași interfață web, dar rulează pe un server public (ex.
  un VPS cu Dokploy). NU are imprimantă; primește fișiere, ține o coadă de
  joburi și le servește unui agent. Nu rulează comenzi CUPS.

- ``agent``  — rulează pe Pi și NU pornește server web. Deschide doar
  conexiuni *spre exterior*: întreabă periodic serverul ``cloud`` dacă are
  joburi, descarcă fișierul, îl printează local cu ``lp`` și raportează
  înapoi. Pi-ul nu trebuie expus deloc pe internet — doar iese.

Modelul cloud + agent înlocuiește tunelul: aplicația web stă în cloud
(Dokploy îi dă domeniu + HTTPS), iar Pi-ul își *trage* singur joburile.

Alte particularități:
- randarea PDF pentru previzualizare se face în browser (PDF.js)
- fișierele încărcate sunt temporare (se șterg automat); doar istoricul
  printărilor (nume, dată, opțiuni) e păstrat într-o bază SQLite
- autentificare opțională (login) prin CLOUDPRINT_PASSWORD — obligatorie
  când aplicația e publică (modul cloud)
"""

import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import tempfile
import time
import uuid
from datetime import timedelta
from pathlib import Path

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

# local | cloud | agent — vezi docstring-ul de sus
MODE = os.environ.get("CLOUDPRINT_MODE", "local").strip().lower()

BASE_DIR = Path(__file__).resolve().parent
# în cloud (Dokploy) datele persistente pot sta pe un volum montat separat
DATA_DIR = Path(os.environ.get("CLOUDPRINT_DATA_DIR", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "cloudprint.db"

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".txt"}
MAX_UPLOAD_MB = 50
UPLOAD_TTL_SECONDS = 6 * 60 * 60  # fișierele temporare se șterg după 6h
AGENT_OFFLINE_AFTER = 60  # secunde fără raport => considerăm agentul offline

PAGE_RANGE_RE = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")
FILE_ID_RE = re.compile(r"^[0-9a-f]{32}\.[a-z]+$")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+-\d+$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# nume/tip original per fișier temporar. În modul local rămâne doar în memorie
# (fișierele oricum sunt efemere); în modul cloud se persistă în tabelul
# ``uploads`` fiindcă /api/print vine ca cerere separată, posibil pe alt worker.
_uploads = {}


# ------------------------------------------------------------------ autentificare

# Autentificarea e OPȚIONALĂ în modul local (rețea de încredere), dar
# OBLIGATORIE în cloud. Se activează setând CLOUDPRINT_PASSWORD.
AUTH_PASSWORD = os.environ.get("CLOUDPRINT_PASSWORD")
AUTH_USER = os.environ.get("CLOUDPRINT_USER", "admin")

# Token cu care agentul (Pi-ul) se autentifică la serverul cloud. Fără el,
# endpoint-urile /agent/* refuză orice cerere (nu le lăsăm deschise public).
AGENT_TOKEN = os.environ.get("CLOUDPRINT_AGENT_TOKEN")


def _load_secret_key():
    """Cheie pentru semnarea cookie-urilor de sesiune, stabilă între restarturi."""
    env = os.environ.get("CLOUDPRINT_SECRET")
    if env:
        return env
    path = DATA_DIR / "secret_key"
    try:
        if path.exists():
            return path.read_text().strip()
        key = secrets.token_hex(32)
        path.write_text(key)
        path.chmod(0o600)
        return key
    except OSError:
        # nu putem scrie pe disc — cheie doar în memorie (sesiunile nu
        # supraviețuiesc restartului, dar aplicația funcționează)
        return secrets.token_hex(32)


app.secret_key = _load_secret_key()
app.permanent_session_lifetime = timedelta(days=30)


@app.before_request
def gate_request():
    # Endpoint-urile pentru agent au autentificare proprie (token), separată
    # de login-ul utilizatorilor. Există doar în modul cloud.
    if request.path.startswith("/agent/"):
        if MODE != "cloud":
            abort(404)
        if not AGENT_TOKEN:
            return jsonify({"error": "Agent token neconfigurat pe server."}), 503
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not hmac.compare_digest(token, AGENT_TOKEN):
            return jsonify({"error": "Token invalid."}), 401
        return  # autentificat ca agent — nu mai cerem login de utilizator

    if not AUTH_PASSWORD:
        return  # autentificare dezactivată (mod LAN)
    if session.get("auth"):
        return
    if request.endpoint in {"login", "static"}:
        return
    if request.path.startswith("/api/") or request.path.startswith("/files/"):
        return jsonify({"error": "Neautentificat."}), 401
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not AUTH_PASSWORD:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        user = request.form.get("user", "")
        pw = request.form.get("password", "")
        # comparație în timp constant, ca să nu se poată ghici prin timing
        ok = hmac.compare_digest(user, AUTH_USER) and hmac.compare_digest(
            pw, AUTH_PASSWORD
        )
        if ok:
            session["auth"] = True
            session.permanent = True
            return redirect(url_for("index"))
        time.sleep(1)  # încetinește încercările repetate
        error = "Utilizator sau parolă greșite."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------------ bază de date

def get_db():
    """Conexiune SQLite per-request (Flask rulează multi-thread)."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        # dacă mai multe cereri scriu simultan, așteaptă deblocarea în loc să crape
        g.db.execute("PRAGMA busy_timeout = 5000")
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
        CREATE TABLE IF NOT EXISTS history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            type       TEXT NOT NULL,
            printer    TEXT,
            job_id     TEXT,
            options    TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        """
    )
    if MODE == "cloud":
        # coada de joburi + starea agentului, folosite doar de serverul cloud
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id    TEXT NOT NULL,
                name       TEXT NOT NULL,
                type       TEXT,
                printer    TEXT,
                options    TEXT NOT NULL,
                status     TEXT NOT NULL,   -- queued|printing|done|error|canceled
                cups_id    TEXT,
                error      TEXT,
                created_at REAL NOT NULL,
                claimed_at REAL,
                updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS uploads (
                file_id    TEXT PRIMARY KEY,
                name       TEXT,
                type       TEXT,
                size       INTEGER,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS cancels (
                cups_id    TEXT PRIMARY KEY,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS agent_state (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                printers        TEXT,
                default_printer TEXT,
                queue           TEXT,
                updated_at      REAL
            );
            """
        )
    conn.commit()
    conn.close()


if MODE in {"local", "cloud"}:
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


def collect_printers():
    """Citește imprimantele CUPS locale: (printers, default, error)."""
    ok, out, err = run_command(["lpstat", "-p"])
    if not ok and not out:
        return [], None, err.strip()

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

    return printers, default, None


def collect_queue():
    """Citește coada CUPS locală (lpstat -o): (jobs, error)."""
    ok, out, err = run_command(["lpstat", "-o"])
    if not ok and err:
        return [], err.strip()

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
    return jobs, None


def validate_print_options(data):
    """Validează și normalizează opțiunile de printare.

    Întoarce ``(printer, options)`` sau ridică ``ValueError`` cu un mesaj
    prietenos dacă ceva e invalid. Opțiunile întoarse sunt deja curățate,
    deci pot fi stocate în coadă și transformate în argumente ``lp`` mai târziu.
    """
    printer = data.get("printer") or None
    if printer and not re.match(r"^[A-Za-z0-9_.-]+$", printer):
        raise ValueError("Nume de imprimantă invalid.")

    try:
        copies = int(data.get("copies", 1))
    except (TypeError, ValueError):
        copies = 1
    copies = max(1, min(copies, 99))

    page_range = (data.get("page_range") or "").replace(" ", "")
    if page_range and not PAGE_RANGE_RE.match(page_range):
        raise ValueError("Interval de pagini invalid. Exemplu: 1-3,5,8")

    media = data.get("media")
    media = media if media in {"A4", "A5", "Letter", "Legal"} else "A4"

    quality = data.get("quality")
    quality = quality if quality in {"draft", "normal", "high"} else "normal"

    options = {
        "copies": copies,
        "grayscale": bool(data.get("grayscale")),
        "duplex": bool(data.get("duplex")),
        "duplex_edge": "short" if data.get("duplex_edge") == "short" else "long",
        "landscape": bool(data.get("landscape")),
        "media": media,
        "quality": quality,
        "page_range": page_range,
        "fit_to_page": bool(data.get("fit_to_page")),
    }
    return printer, options


def build_lp_args(printer, options, file_path, title):
    """Construiește lista de argumente pentru comanda ``lp``."""
    args = ["lp"]
    if printer:
        args += ["-d", printer]
    args += ["-n", str(options["copies"])]
    args += ["-t", (title or "")[:120]]

    if options["duplex"]:
        args += ["-o", f"sides=two-sided-{options['duplex_edge']}-edge"]
    else:
        args += ["-o", "sides=one-sided"]

    if options["grayscale"]:
        args += ["-o", "print-color-mode=monochrome", "-o", "ColorModel=Gray"]

    if options["page_range"]:
        args += ["-o", f"page-ranges={options['page_range']}"]

    args += ["-o", f"media={options['media']}"]

    if options["landscape"]:
        args += ["-o", "landscape"]

    level = {"draft": "3", "normal": "4", "high": "5"}[options["quality"]]
    args += ["-o", f"print-quality={level}"]

    if options["fit_to_page"]:
        args += ["-o", "fit-to-page"]

    args.append(str(file_path))
    return args


def get_upload_info(file_id):
    """Nume/tip original pentru un fișier încărcat (memorie în local, DB în cloud)."""
    if MODE == "cloud":
        row = get_db().execute(
            "SELECT name, type FROM uploads WHERE file_id = ?", (file_id,)
        ).fetchone()
        return {"name": row["name"], "type": row["type"]} if row else {}
    return _uploads.get(file_id, {})


def delete_upload(file_id):
    """Șterge fișierul temporar și metadatele lui."""
    try:
        (UPLOAD_DIR / file_id).unlink(missing_ok=True)
    except OSError:
        pass
    _uploads.pop(file_id, None)
    if MODE == "cloud":
        try:
            db = get_db()
            db.execute("DELETE FROM uploads WHERE file_id = ?", (file_id,))
            db.commit()
        except sqlite3.Error:
            pass


def cleanup_old_uploads():
    """Șterge fișierele temporare mai vechi decât TTL.

    În cloud nu atingem fișierele joburilor încă neterminate (queued/printing),
    ca să nu dispară de sub agent înainte să apuce să le tragă.
    """
    now = time.time()
    protected = set()
    if MODE == "cloud":
        try:
            protected = {
                r["file_id"]
                for r in get_db().execute(
                    "SELECT file_id FROM jobs WHERE status IN ('queued', 'printing')"
                )
            }
        except sqlite3.Error:
            pass
    for path in UPLOAD_DIR.iterdir():
        if path.name in protected:
            continue
        try:
            if now - path.stat().st_mtime > UPLOAD_TTL_SECONDS:
                path.unlink()
                _uploads.pop(path.name, None)
        except OSError:
            pass


def record_history(name, type_, printer, job_id, options):
    db = get_db()
    db.execute(
        "INSERT INTO history (name, type, printer, job_id, options, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, type_, printer, job_id, json.dumps(options), time.time()),
    )
    db.commit()


# ------------------------------------------------------------------ pagini

@app.route("/")
def index():
    return render_template("index.html", auth_enabled=bool(AUTH_PASSWORD))


# ------------------------------------------------------------------ imprimante

@app.route("/api/printers")
def list_printers():
    if MODE == "cloud":
        state = get_db().execute(
            "SELECT printers, default_printer, updated_at FROM agent_state WHERE id = 1"
        ).fetchone()
        if not state or not state["updated_at"]:
            return jsonify(
                {
                    "printers": [],
                    "default": None,
                    "error": "Niciun agent (Raspberry Pi) conectat încă.",
                }
            )
        error = None
        if time.time() - state["updated_at"] > AGENT_OFFLINE_AFTER:
            error = "Agentul (Raspberry Pi) pare offline — nu a mai raportat de o vreme."
        return jsonify(
            {
                "printers": json.loads(state["printers"] or "[]"),
                "default": state["default_printer"],
                "error": error,
            }
        )

    printers, default, error = collect_printers()
    return jsonify({"printers": printers, "default": default, "error": error})


# ------------------------------------------------------------------ fișiere temporare

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
                {"error": "Format neacceptat. Formate permise: PDF, JPG, PNG, GIF, TXT."}
            ),
            400,
        )

    file_id = uuid.uuid4().hex + ext
    dest = UPLOAD_DIR / file_id
    file.save(dest)
    size = dest.stat().st_size
    type_ = ext.lstrip(".")

    if MODE == "cloud":
        db = get_db()
        db.execute(
            "INSERT INTO uploads (file_id, name, type, size, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (file_id, file.filename, type_, size, time.time()),
        )
        db.commit()
    else:
        _uploads[file_id] = {"name": file.filename, "type": type_}

    return jsonify(
        {
            "id": file_id,
            "name": file.filename,
            "type": type_,
            "size": size,
            "url": f"/files/{file_id}",
        }
    )


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

    info = get_upload_info(file_id)

    try:
        printer, options = validate_print_options(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    title = info.get("name", file_id)

    if MODE == "cloud":
        # nu printăm aici — punem jobul în coadă, îl ia agentul de pe Pi
        db = get_db()
        cur = db.execute(
            "INSERT INTO jobs (file_id, name, type, printer, options, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'queued', ?)",
            (file_id, title, info.get("type", ""), printer, json.dumps(options), time.time()),
        )
        db.commit()
        return jsonify(
            {"job_id": f"q{cur.lastrowid}", "title": title, "copies": options["copies"]}
        )

    # modul local: printăm direct
    args = build_lp_args(printer, options, UPLOAD_DIR / file_id, title)
    ok, out, err = run_command(args, timeout=30)
    if not ok:
        return jsonify({"error": err.strip() or "Comanda lp a eșuat."}), 502

    job_id = None
    match = re.search(r"request id is (\S+)", out)
    if match:
        job_id = match.group(1)

    record_history(title, info.get("type", ""), printer, job_id, options)
    return jsonify({"job_id": job_id, "title": title, "copies": options["copies"]})


# ------------------------------------------------------------------ istoric

@app.route("/api/history")
def list_history():
    rows = get_db().execute(
        "SELECT * FROM history ORDER BY created_at DESC LIMIT 200"
    ).fetchall()
    items = [
        {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "printer": r["printer"],
            "options": json.loads(r["options"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return jsonify({"history": items})


@app.route("/api/history", methods=["DELETE"])
def clear_history():
    db = get_db()
    db.execute("DELETE FROM history")
    db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ coadă (live)

@app.route("/api/jobs")
def list_jobs():
    if MODE == "cloud":
        db = get_db()
        jobs = []
        # joburi din coada noastră, încă nepreluate/în lucru de agent
        for r in db.execute(
            "SELECT id, name, printer FROM jobs "
            "WHERE status IN ('queued', 'printing') ORDER BY created_at"
        ):
            jobs.append(
                {
                    "id": f"q{r['id']}",
                    "printer": r["printer"] or "",
                    "number": "—",
                    "title": f"{r['name']} · în așteptare",
                    "size": None,
                }
            )
        # coada CUPS reală, așa cum a raportat-o agentul
        titles = {
            row["job_id"]: row["name"]
            for row in db.execute(
                "SELECT job_id, name FROM history WHERE job_id IS NOT NULL"
            )
        }
        state = db.execute(
            "SELECT queue FROM agent_state WHERE id = 1"
        ).fetchone()
        if state and state["queue"]:
            for q in json.loads(state["queue"]):
                jobs.append(
                    {
                        "id": q["id"],
                        "printer": q.get("printer") or "",
                        "number": q.get("number"),
                        "title": titles.get(q["id"]),
                        "size": q.get("size"),
                    }
                )
        return jsonify({"jobs": jobs, "error": None})

    jobs, error = collect_queue()
    if error and not jobs:
        return jsonify({"jobs": [], "error": error})

    titles = {
        r["job_id"]: r["name"]
        for r in get_db().execute(
            "SELECT job_id, name FROM history WHERE job_id IS NOT NULL"
        ).fetchall()
    }
    for job in jobs:
        job["title"] = titles.get(job["id"])
    return jsonify({"jobs": jobs, "error": None})


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    if MODE == "cloud":
        db = get_db()
        # job încă în coada noastră ("q<rowid>") — îl anulăm pe loc
        if job_id.startswith("q") and job_id[1:].isdigit():
            row = db.execute(
                "SELECT status FROM jobs WHERE id = ?", (int(job_id[1:]),)
            ).fetchone()
            if not row:
                return jsonify({"error": "Jobul nu mai există."}), 404
            if row["status"] == "queued":
                db.execute(
                    "UPDATE jobs SET status = 'canceled', updated_at = ? WHERE id = ?",
                    (time.time(), int(job_id[1:])),
                )
                db.commit()
                return jsonify({"ok": True})
            return jsonify({"error": "Jobul e deja trimis la imprimantă."}), 409
        # altfel e un id CUPS — cerem agentului să-l anuleze la următorul poll
        if not JOB_ID_RE.match(job_id):
            return jsonify({"error": "Id de job invalid."}), 400
        db.execute(
            "INSERT OR IGNORE INTO cancels (cups_id, created_at) VALUES (?, ?)",
            (job_id, time.time()),
        )
        db.commit()
        return jsonify({"ok": True})

    if not JOB_ID_RE.match(job_id):
        return jsonify({"error": "Id de job invalid."}), 400
    ok, _, err = run_command(["cancel", job_id])
    if not ok:
        return jsonify({"error": err.strip() or "Anularea a eșuat."}), 502
    return jsonify({"ok": True})


# ------------------------------------------------------------------ API agent (doar cloud)

if MODE == "cloud":

    @app.route("/agent/next")
    def agent_next():
        """Agentul întreabă: ai un job pentru mine? (+ ce trebuie anulat)"""
        db = get_db()
        row = db.execute(
            "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        job = None
        if row:
            db.execute(
                "UPDATE jobs SET status = 'printing', claimed_at = ? WHERE id = ?",
                (time.time(), row["id"]),
            )
            db.commit()
            job = {
                "id": row["id"],
                "file_id": row["file_id"],
                "printer": row["printer"],
                "title": row["name"],
                "options": json.loads(row["options"]),
            }

        cancels = [r["cups_id"] for r in db.execute("SELECT cups_id FROM cancels")]
        if cancels:
            db.execute("DELETE FROM cancels")
            db.commit()

        return jsonify({"job": job, "cancels": cancels})

    @app.route("/agent/file/<file_id>")
    def agent_file(file_id):
        if not FILE_ID_RE.match(file_id):
            abort(404)
        return send_from_directory(UPLOAD_DIR, file_id)

    @app.route("/agent/jobs/<int:job_id>/status", methods=["POST"])
    def agent_job_status(job_id):
        """Agentul raportează rezultatul unui job."""
        data = request.get_json(silent=True) or {}
        db = get_db()
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return jsonify({"error": "Jobul nu există."}), 404

        now = time.time()
        if data.get("ok"):
            cups_id = data.get("cups_id")
            # scriem în istoric la momentul trimiterii (ca în modul local)
            record_history(
                row["name"], row["type"] or "", row["printer"], cups_id,
                json.loads(row["options"]),
            )
            db.execute(
                "UPDATE jobs SET status = 'done', cups_id = ?, updated_at = ? WHERE id = ?",
                (cups_id, now, job_id),
            )
        else:
            db.execute(
                "UPDATE jobs SET status = 'error', error = ?, updated_at = ? WHERE id = ?",
                (str(data.get("error") or "eroare la printare"), now, job_id),
            )
        db.commit()
        delete_upload(row["file_id"])  # fișierul nu mai e necesar
        return jsonify({"ok": True})

    @app.route("/agent/report", methods=["POST"])
    def agent_report():
        """Agentul raportează imprimantele și coada CUPS locală."""
        data = request.get_json(silent=True) or {}
        db = get_db()
        db.execute(
            "INSERT INTO agent_state (id, printers, default_printer, queue, updated_at) "
            "VALUES (1, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "printers = excluded.printers, default_printer = excluded.default_printer, "
            "queue = excluded.queue, updated_at = excluded.updated_at",
            (
                json.dumps(data.get("printers") or []),
                data.get("default"),
                json.dumps(data.get("queue") or []),
                time.time(),
            ),
        )
        db.commit()
        return jsonify({"ok": True})


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": f"Fișier prea mare. Limita este {MAX_UPLOAD_MB} MB."}), 413


# ------------------------------------------------------------------ agent (client pe Pi)

def run_agent():
    """Bucla agentului: trage joburi de la serverul cloud și le printează local.

    Face doar cereri HTTP *spre exterior* — Pi-ul nu trebuie expus deloc.
    """
    import requests

    base = os.environ.get("CLOUDPRINT_CLOUD_URL", "").rstrip("/")
    token = os.environ.get("CLOUDPRINT_AGENT_TOKEN", "")
    interval = float(os.environ.get("CLOUDPRINT_POLL_INTERVAL", "4"))
    if not base:
        raise SystemExit("Setează CLOUDPRINT_CLOUD_URL (ex. https://print.exemplu.ro).")
    if not token:
        raise SystemExit("Setează CLOUDPRINT_AGENT_TOKEN (același ca pe server).")

    headers = {"Authorization": f"Bearer {token}"}
    http = requests.Session()
    http.headers.update(headers)
    tmpdir = Path(tempfile.mkdtemp(prefix="cloudprint-agent-"))
    last_report = 0.0

    print(f"[CloudPrint agent] conectat la {base}, poll la {interval}s")

    def report_state():
        printers, default, _ = collect_printers()
        queue, _ = collect_queue()
        http.post(
            f"{base}/agent/report",
            json={"printers": printers, "default": default, "queue": queue},
            timeout=30,
        )

    def handle_job(job):
        file_id = job["file_id"]
        dest = tmpdir / file_id
        try:
            resp = http.get(f"{base}/agent/file/{file_id}", timeout=120)
            if resp.status_code != 200:
                _report_result(job["id"], False, None, "descărcarea fișierului a eșuat")
                return
            dest.write_bytes(resp.content)

            args = build_lp_args(job.get("printer"), job["options"], dest, job.get("title"))
            ok, out, err = run_command(args, timeout=60)
            cups_id = None
            if ok:
                match = re.search(r"request id is (\S+)", out)
                if match:
                    cups_id = match.group(1)
            _report_result(job["id"], ok, cups_id, None if ok else (err.strip() or "lp a eșuat"))
        finally:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass

    def _report_result(job_id, ok, cups_id, error):
        try:
            http.post(
                f"{base}/agent/jobs/{job_id}/status",
                json={"ok": ok, "cups_id": cups_id, "error": error},
                timeout=30,
            )
        except requests.RequestException as exc:
            print(f"[CloudPrint agent] nu am putut raporta jobul {job_id}: {exc}")

    while True:
        try:
            now = time.time()
            if now - last_report > 20:
                report_state()
                last_report = now

            resp = http.get(f"{base}/agent/next", timeout=30)
            if resp.status_code == 401:
                print("[CloudPrint agent] token respins de server — verifică CLOUDPRINT_AGENT_TOKEN")
                time.sleep(interval)
                continue
            resp.raise_for_status()
            data = resp.json()

            for cups_id in data.get("cancels", []):
                run_command(["cancel", cups_id])

            job = data.get("job")
            if job:
                handle_job(job)
                continue  # mai întreabă imediat, poate mai sunt joburi
        except requests.RequestException as exc:
            print(f"[CloudPrint agent] eroare de rețea: {exc}")

        time.sleep(interval)


# ------------------------------------------------------------------ pornire

def build_ssl_context():
    """Încarcă certificatul HTTPS dacă există și e valid.

    Dacă certificatul lipsește sau nu poate fi citit (ex. drepturi greșite
    când a fost generat cu sudo), pornim pe http în loc să crăpăm de tot —
    mai bine merge pe http decât să nu meargă deloc.
    """
    cert = BASE_DIR / "certs" / "cert.pem"
    key = BASE_DIR / "certs" / "key.pem"
    if not (cert.exists() and key.exists()):
        return None
    try:
        import ssl

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert), str(key))
        return ctx
    except Exception as exc:  # cert stricat / cheie necitibilă / drepturi
        print(f"[CloudPrint] Nu pot folosi certificatul HTTPS ({exc}).")
        print("[CloudPrint] Pornesc pe http. Rulează ./gen-cert.sh ca userul serviciului.")
        return None


if __name__ == "__main__":
    if MODE == "agent":
        run_agent()
    else:
        port = int(os.environ.get("PORT", "8080"))
        # în cloud, TLS îl termină reverse proxy-ul (Traefik/Dokploy) — http simplu aici
        ssl_context = None if MODE == "cloud" else build_ssl_context()
        scheme = "https" if ssl_context else "http"
        print(f"CloudPrint ({MODE}) pornește pe {scheme}://0.0.0.0:{port}")
        app.run(host="0.0.0.0", port=port, threaded=True, ssl_context=ssl_context)

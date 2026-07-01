"""
CodeHost — self-hosted mini PaaS for running your own bots/APIs.

A single-file Flask backend that lets an admin (protected by ADMIN_KEY):
  - Create/manage code "projects" (folders of files)
  - Edit files in a browser code editor
  - Import a project straight from a GitHub repo URL
  - Manage per-project environment variables (.env)
  - Run / stop a project as a subprocess (auto pip install -r requirements.txt)
  - Stream live logs
  - Download a project as a ZIP

Deploy this on Render (or any host) — see README.md for step-by-step instructions.

IMPORTANT: run with a single worker (gunicorn -w 1) because process state is
kept in memory. See Procfile.
"""

import os
import io
import json
import shutil
import sqlite3
import hmac
import subprocess
import threading
import time
import zipfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Flask, request, session, redirect, url_for, render_template,
    jsonify, send_file, abort, g
)

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
PROJECTS_DIR = DATA_DIR / "projects"
DB_PATH = DATA_DIR / "codehost.db"

ADMIN_KEY = os.environ.get("ADMIN_KEY", "change-me-admin-key")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-secret-change-me")

MAX_LOG_BYTES = 2 * 1024 * 1024  # keep last 2MB of logs per project
RUN_ENTRY_CANDIDATES = ["main.py", "bot.py", "app.py", "run.py", "server.py", "index.js"]

DATA_DIR.mkdir(parents=True, exist_ok=True)
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB upload cap

# In-memory registry of running processes: {project_id: {"proc": Popen, "log_path": Path, "started_at": str}}
RUNNING = {}
RUNNING_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Database helpers (SQLite — zero external dependencies)
# --------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            entry_file TEXT,
            github_url TEXT,
            env_json TEXT DEFAULT '{}',
            status TEXT DEFAULT 'stopped',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


init_db()


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def safe_join(root: Path, rel_path: str) -> Path:
    """Resolve rel_path under root, refusing any path traversal outside it."""
    rel_path = (rel_path or "").strip().lstrip("/")
    candidate = (root / rel_path).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        abort(400, "Invalid path")
    return candidate


def log_path_for(project_id: str) -> Path:
    return project_dir(project_id) / ".codehost_run.log"


def env_path_for(project_id: str) -> Path:
    return project_dir(project_id) / ".env"


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

def login_required(view):
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    wrapped.__name__ = view.__name__
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        key = request.form.get("admin_key", "")
        if hmac.compare_digest(key, ADMIN_KEY):
            session["authenticated"] = True
            session.permanent = True
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid admin key")
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

@app.route("/")
@login_required
def dashboard():
    db = get_db()
    rows = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    projects = [dict(r) for r in rows]
    for p in projects:
        p["running"] = p["id"] in RUNNING
    return render_template("dashboard.html", projects=projects)


@app.route("/projects/<project_id>")
@login_required
def project_page(project_id):
    db = get_db()
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        abort(404)
    project = dict(row)
    project["running"] = project_id in RUNNING
    return render_template("project.html", project=project)


# --------------------------------------------------------------------------
# API: projects CRUD
# --------------------------------------------------------------------------

@app.route("/api/projects", methods=["POST"])
@login_required
def api_create_project():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "New Project").strip()[:80] or "New Project"
    project_id = uuid.uuid4().hex[:12]
    pdir = project_dir(project_id)
    pdir.mkdir(parents=True, exist_ok=True)

    starter = pdir / "main.py"
    starter.write_text(
        "# Entry point for your project.\n"
        "# Add your bot/API code here, then hit Run.\n\n"
        "print(\"Hello from CodeHost!\")\n"
    )

    db = get_db()
    db.execute(
        "INSERT INTO projects (id, name, entry_file, github_url, env_json, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, name, "main.py", None, "{}", "stopped", datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    return jsonify({"id": project_id, "name": name}), 201


@app.route("/api/projects/<project_id>", methods=["DELETE"])
@login_required
def api_delete_project(project_id):
    _stop_process(project_id)
    shutil.rmtree(project_dir(project_id), ignore_errors=True)
    db = get_db()
    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/projects/<project_id>/rename", methods=["POST"])
@login_required
def api_rename_project(project_id):
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()[:80]
    if not name:
        return jsonify({"error": "name required"}), 400
    db = get_db()
    db.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/projects/<project_id>/entry", methods=["POST"])
@login_required
def api_set_entry(project_id):
    data = request.get_json(force=True, silent=True) or {}
    entry_file = (data.get("entry_file") or "").strip()
    db = get_db()
    db.execute("UPDATE projects SET entry_file = ? WHERE id = ?", (entry_file, project_id))
    db.commit()
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# API: file browser / editor
# --------------------------------------------------------------------------

@app.route("/api/projects/<project_id>/files", methods=["GET"])
@login_required
def api_list_files(project_id):
    pdir = project_dir(project_id)
    if not pdir.exists():
        abort(404)
    files = []
    for path in sorted(pdir.rglob("*")):
        if path.is_dir():
            continue
        if path.name.startswith(".codehost") or path.name == ".env" or ".git" in path.parts:
            continue
        rel = str(path.relative_to(pdir))
        files.append({"path": rel, "size": path.stat().st_size})
    return jsonify({"files": files})


@app.route("/api/projects/<project_id>/file", methods=["GET"])
@login_required
def api_read_file(project_id):
    rel = request.args.get("path", "")
    target = safe_join(project_dir(project_id), rel)
    if not target.exists() or target.is_dir():
        abort(404)
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": str(exc)}), 400
    return jsonify({"path": rel, "content": content})


@app.route("/api/projects/<project_id>/file", methods=["POST"])
@login_required
def api_write_file(project_id):
    data = request.get_json(force=True, silent=True) or {}
    rel = data.get("path", "")
    content = data.get("content", "")
    if not rel:
        return jsonify({"error": "path required"}), 400
    target = safe_join(project_dir(project_id), rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/projects/<project_id>/file", methods=["DELETE"])
@login_required
def api_delete_file(project_id):
    rel = request.args.get("path", "")
    target = safe_join(project_dir(project_id), rel)
    if target.exists():
        target.unlink()
    return jsonify({"ok": True})


@app.route("/api/projects/<project_id>/upload", methods=["POST"])
@login_required
def api_upload_files(project_id):
    pdir = project_dir(project_id)
    pdir.mkdir(parents=True, exist_ok=True)
    uploaded = request.files.getlist("files")
    saved = []
    for f in uploaded:
        rel_path = f.filename or "file.txt"
        target = safe_join(pdir, rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        f.save(target)
        saved.append(rel_path)
    return jsonify({"ok": True, "saved": saved})


# --------------------------------------------------------------------------
# API: GitHub import
# --------------------------------------------------------------------------

@app.route("/api/projects/<project_id>/github", methods=["POST"])
@login_required
def api_github_import(project_id):
    data = request.get_json(force=True, silent=True) or {}
    repo_url = (data.get("repo_url") or "").strip()
    if not repo_url:
        return jsonify({"error": "repo_url required"}), 400

    pdir = project_dir(project_id)
    for child in pdir.glob("*"):
        if child.name in (".env", ".codehost_run.log"):
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink()

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(pdir)],
            capture_output=True, text=True, timeout=120,
        )
    except Exception as exc:
        return jsonify({"error": f"clone failed: {exc}"}), 500

    if result.returncode != 0:
        return jsonify({"error": result.stderr.strip() or "git clone failed"}), 400

    shutil.rmtree(pdir / ".git", ignore_errors=True)

    entry_file = None
    for candidate in RUN_ENTRY_CANDIDATES:
        if (pdir / candidate).exists():
            entry_file = candidate
            break

    db = get_db()
    db.execute(
        "UPDATE projects SET github_url = ?, entry_file = COALESCE(?, entry_file) WHERE id = ?",
        (repo_url, entry_file, project_id),
    )
    db.commit()
    return jsonify({"ok": True, "entry_file": entry_file})


# --------------------------------------------------------------------------
# API: environment variables
# --------------------------------------------------------------------------

@app.route("/api/projects/<project_id>/env", methods=["GET"])
@login_required
def api_get_env(project_id):
    db = get_db()
    row = db.execute("SELECT env_json FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        abort(404)
    env_vars = json.loads(row["env_json"] or "{}")
    return jsonify({"env": env_vars})


@app.route("/api/projects/<project_id>/env", methods=["POST"])
@login_required
def api_set_env(project_id):
    data = request.get_json(force=True, silent=True) or {}
    env_vars = data.get("env", {})
    if not isinstance(env_vars, dict):
        return jsonify({"error": "env must be an object"}), 400
    clean = {str(k): str(v) for k, v in env_vars.items() if k}

    db = get_db()
    db.execute("UPDATE projects SET env_json = ? WHERE id = ?", (json.dumps(clean), project_id))
    db.commit()

    env_file = env_path_for(project_id)
    with env_file.open("w") as fh:
        for k, v in clean.items():
            fh.write(f'{k}={v}\n')

    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# Process execution: run / stop / logs
# --------------------------------------------------------------------------

def _append_log(project_id: str, message: str):
    lp = log_path_for(project_id)
    lp.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%H:%M:%S")
    with lp.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {message}\n")
    if lp.exists() and lp.stat().st_size > MAX_LOG_BYTES:
        data = lp.read_bytes()[-MAX_LOG_BYTES:]
        lp.write_bytes(data)


def _stream_process_output(project_id: str, proc: subprocess.Popen):
    try:
        for line in iter(proc.stdout.readline, b""):
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            _append_log(project_id, text)
    except Exception as exc:  # pragma: no cover
        _append_log(project_id, f"[log-reader-error] {exc}")
    finally:
        proc.wait()
        _append_log(project_id, f"[process exited with code {proc.returncode}]")
        with RUNNING_LOCK:
            RUNNING.pop(project_id, None)
        _set_status(project_id, "stopped")


def _set_status(project_id: str, status: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))
    conn.commit()
    conn.close()


def _detect_entry(pdir: Path, configured: str | None) -> str | None:
    if configured and (pdir / configured).exists():
        return configured
    for candidate in RUN_ENTRY_CANDIDATES:
        if (pdir / candidate).exists():
            return candidate
    return None


def _run_project_thread(project_id: str, entry_file: str, env_vars: dict):
    pdir = project_dir(project_id)
    lp = log_path_for(project_id)
    lp.write_text("")  # reset log

    run_env = os.environ.copy()
    run_env.update(env_vars)
    run_env["PYTHONUNBUFFERED"] = "1"

    requirements = pdir / "requirements.txt"
    if requirements.exists():
        _append_log(project_id, "Installing dependencies from requirements.txt ...")
        install = subprocess.run(
            ["pip", "install", "--no-input", "-r", str(requirements)],
            cwd=str(pdir), capture_output=True, text=True, env=run_env,
        )
        for out_line in (install.stdout + install.stderr).splitlines():
            _append_log(project_id, out_line)
        if install.returncode != 0:
            _append_log(project_id, "[dependency install failed — attempting to run anyway]")

    package_json = pdir / "package.json"
    if entry_file.endswith(".js") and package_json.exists():
        _append_log(project_id, "Installing npm dependencies ...")
        npm_install = subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund"],
            cwd=str(pdir), capture_output=True, text=True, env=run_env,
        )
        for out_line in (npm_install.stdout + npm_install.stderr).splitlines():
            _append_log(project_id, out_line)

    if entry_file.endswith(".js"):
        cmd = ["node", entry_file]
    else:
        cmd = ["python3", entry_file]

    _append_log(project_id, f"Starting: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd, cwd=str(pdir), env=run_env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        _append_log(project_id, f"[failed to start process] {exc}")
        with RUNNING_LOCK:
            RUNNING.pop(project_id, None)
        _set_status(project_id, "stopped")
        return

    with RUNNING_LOCK:
        RUNNING[project_id] = {"proc": proc, "started_at": datetime.now(timezone.utc).isoformat()}
    _set_status(project_id, "running")

    _stream_process_output(project_id, proc)


@app.route("/api/projects/<project_id>/run", methods=["POST"])
@login_required
def api_run_project(project_id):
    if project_id in RUNNING:
        return jsonify({"error": "already running"}), 400

    db = get_db()
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        abort(404)

    pdir = project_dir(project_id)
    entry_file = _detect_entry(pdir, row["entry_file"])
    if not entry_file:
        return jsonify({"error": "No entry file found (expected main.py, bot.py, app.py, run.py, server.py or index.js)"}), 400

    env_vars = json.loads(row["env_json"] or "{}")

    thread = threading.Thread(
        target=_run_project_thread, args=(project_id, entry_file, env_vars), daemon=True
    )
    thread.start()
    time.sleep(0.3)  # give the thread a moment to register in RUNNING
    return jsonify({"ok": True, "entry_file": entry_file})


def _stop_process(project_id: str):
    with RUNNING_LOCK:
        entry = RUNNING.get(project_id)
    if not entry:
        return False
    proc = entry["proc"]
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:
        pass
    return True


@app.route("/api/projects/<project_id>/stop", methods=["POST"])
@login_required
def api_stop_project(project_id):
    stopped = _stop_process(project_id)
    if not stopped:
        return jsonify({"error": "not running"}), 400
    return jsonify({"ok": True})


@app.route("/api/projects/<project_id>/logs", methods=["GET"])
@login_required
def api_get_logs(project_id):
    lp = log_path_for(project_id)
    if not lp.exists():
        return jsonify({"log": "", "running": project_id in RUNNING})
    text = lp.read_text(encoding="utf-8", errors="replace")
    tail = text[-100_000:]
    return jsonify({"log": tail, "running": project_id in RUNNING})


@app.route("/api/projects/<project_id>/status", methods=["GET"])
@login_required
def api_get_status(project_id):
    return jsonify({"running": project_id in RUNNING})


# --------------------------------------------------------------------------
# ZIP download
# --------------------------------------------------------------------------

@app.route("/api/projects/<project_id>/download")
@login_required
def api_download_project(project_id):
    pdir = project_dir(project_id)
    if not pdir.exists():
        abort(404)

    db = get_db()
    row = db.execute("SELECT name FROM projects WHERE id = ?", (project_id,)).fetchone()
    name = (row["name"] if row else project_id).replace(" ", "_")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in pdir.rglob("*"):
            if path.is_dir():
                continue
            if path.name in (".env", ".codehost_run.log") or ".git" in path.parts:
                continue
            zf.write(path, path.relative_to(pdir))
    buf.seek(0)
    return send_file(
        buf, mimetype="application/zip", as_attachment=True,
        download_name=f"{name}.zip",
    )


# --------------------------------------------------------------------------
# Health check (used by Render)
# --------------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

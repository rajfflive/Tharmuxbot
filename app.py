"""
CodeHost — self-hosted mini PaaS for running your own bots/APIs.
MongoDB-backed, persistent across restarts. Auto-ping keeps Render awake.
Proxy injects URL-rewriting shim so bot admin panels work correctly.
"""

import os
import io
import json
import re
import shutil
import hmac
import subprocess
import threading
import time
import zipfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import (
    Flask, request, session, redirect, url_for, render_template,
    jsonify, send_file, abort, Response
)
from pymongo import MongoClient, ASCENDING
from pymongo.errors import ConnectionFailure

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
PROJECTS_DIR = DATA_DIR / "projects"

ADMIN_KEY = os.environ.get("ADMIN_KEY", "change-me-admin-key")
MONGODB_URI = os.environ.get("MONGODB_URI", "")

MAX_LOG_BYTES = 2 * 1024 * 1024
RUN_ENTRY_CANDIDATES = ["main.py", "bot.py", "app.py", "run.py", "server.py", "index.js"]
BASE_PORT = 6000

DATA_DIR.mkdir(parents=True, exist_ok=True)
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# MongoDB setup
# --------------------------------------------------------------------------

_mongo_client = None
_db = None


def get_mongo():
    global _mongo_client, _db
    if _db is not None:
        return _db
    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI env var is not set")
    _mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    _mongo_client.admin.command("ping")
    _db = _mongo_client["codehost"]
    _db.projects.create_index("slug")
    _db.files.create_index([("project_id", ASCENDING), ("path", ASCENDING)], unique=True)
    _db.config.create_index("key", unique=True)
    return _db


def _config_get(key: str, default=None):
    try:
        doc = get_mongo().config.find_one({"key": key})
        return doc["value"] if doc else default
    except Exception:
        return default


def _config_set(key: str, value):
    get_mongo().config.update_one({"key": key}, {"$set": {"value": value}}, upsert=True)


# --------------------------------------------------------------------------
# Stable SECRET_KEY from MongoDB
# --------------------------------------------------------------------------

def _get_or_create_secret_key() -> str:
    env_key = os.environ.get("SECRET_KEY", "")
    if env_key and env_key not in ("", "dev-insecure-secret-change-me"):
        return env_key
    try:
        stored = _config_get("secret_key")
        if stored:
            return stored
        new_key = uuid.uuid4().hex + uuid.uuid4().hex
        _config_set("secret_key", new_key)
        return new_key
    except Exception:
        return env_key or uuid.uuid4().hex


SECRET_KEY = _get_or_create_secret_key()

# --------------------------------------------------------------------------
# Flask app
# --------------------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30

RUNNING = {}
RUNNING_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Project helpers
# --------------------------------------------------------------------------

def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def safe_join(root: Path, rel_path: str) -> Path:
    rel_path = (rel_path or "").strip().lstrip("/")
    candidate = (root / rel_path).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        abort(400, "Invalid path")
    return candidate


def log_path_for(project_id: str) -> Path:
    return project_dir(project_id) / ".codehost_run.log"


def _next_free_port() -> int:
    db = get_mongo()
    result = db.projects.find_one({}, sort=[("internal_port", -1)], projection={"internal_port": 1})
    current_max = result["internal_port"] if result and result.get("internal_port") else BASE_PORT - 1
    return max(current_max + 1, BASE_PORT)


# --------------------------------------------------------------------------
# File storage in MongoDB
# --------------------------------------------------------------------------

def mongo_save_file(project_id: str, rel_path: str, content: str):
    get_mongo().files.update_one(
        {"project_id": project_id, "path": rel_path},
        {"$set": {"content": content, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )


def mongo_delete_file(project_id: str, rel_path: str):
    get_mongo().files.delete_one({"project_id": project_id, "path": rel_path})


def mongo_list_files(project_id: str):
    return list(get_mongo().files.find(
        {"project_id": project_id},
        {"path": 1, "content": 1, "_id": 0},
    ))


def mongo_read_file(project_id: str, rel_path: str):
    doc = get_mongo().files.find_one({"project_id": project_id, "path": rel_path})
    return doc["content"] if doc else None


def mongo_delete_all_files(project_id: str):
    get_mongo().files.delete_many({"project_id": project_id})


def _restore_project_to_disk(project_id: str):
    pdir = project_dir(project_id)
    pdir.mkdir(parents=True, exist_ok=True)
    for doc in mongo_list_files(project_id):
        target = pdir / doc["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(doc["content"], encoding="utf-8")
        except Exception:
            pass


def _restore_all_on_startup():
    try:
        db = get_mongo()
        for proj in db.projects.find({}, {"_id": 1}):
            _restore_project_to_disk(proj["_id"])
    except Exception as exc:
        print(f"[startup] File restore skipped: {exc}")


# --------------------------------------------------------------------------
# Auto-ping (keeps Render free tier awake)
# --------------------------------------------------------------------------

PING_URL = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PING_URL", "")
PING_INTERVAL = int(os.environ.get("PING_INTERVAL_SEC", "240"))


def _auto_ping_worker():
    if not PING_URL:
        return
    print(f"[auto-ping] Enabled — pinging {PING_URL}/healthz every {PING_INTERVAL}s")
    while True:
        time.sleep(PING_INTERVAL)
        try:
            requests.get(f"{PING_URL.rstrip('/')}/healthz", timeout=10)
        except Exception as exc:
            print(f"[auto-ping] Error: {exc}")


threading.Thread(target=_auto_ping_worker, daemon=True).start()
_restore_all_on_startup()

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
    db = get_mongo()
    projects = list(db.projects.find({}, sort=[("created_at", -1)]))
    for p in projects:
        p["id"] = p.pop("_id")
        p["running"] = p["id"] in RUNNING
    return render_template("dashboard.html", projects=projects)


@app.route("/projects/<project_id>")
@login_required
def project_page(project_id):
    db = get_mongo()
    proj = db.projects.find_one({"_id": project_id})
    if not proj:
        abort(404)
    project = dict(proj)
    project["id"] = project.pop("_id")
    project["running"] = project_id in RUNNING
    ident = project.get("slug") or project_id
    project["public_url"] = request.host_url.rstrip("/") + url_for("public_proxy_root", ident=ident)
    return render_template("project.html", project=project)


# --------------------------------------------------------------------------
# API: projects CRUD
# --------------------------------------------------------------------------

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


@app.route("/api/projects", methods=["POST"])
@login_required
def api_create_project():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "New Project").strip()[:80] or "New Project"
    project_id = uuid.uuid4().hex[:12]
    pdir = project_dir(project_id)
    pdir.mkdir(parents=True, exist_ok=True)

    starter_content = (
        "# Entry point for your project.\n"
        "# Add your code here, then hit Run.\n\n"
        "print(\"Hello from CodeHost!\")\n"
    )
    (pdir / "main.py").write_text(starter_content, encoding="utf-8")
    mongo_save_file(project_id, "main.py", starter_content)

    internal_port = _next_free_port()
    db = get_mongo()

    # Auto-derive slug from project name so the public URL is human-readable.
    # e.g. name "My Bot" → slug "my-bot" → /pub/my-bot/
    slug_base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or project_id
    slug = slug_base
    suffix = 1
    while db.projects.find_one({"slug": slug}):
        slug = f"{slug_base}-{suffix}"
        suffix += 1

    db.projects.insert_one({
        "_id": project_id,
        "name": name,
        "entry_file": "main.py",
        "github_url": None,
        "env": {},
        "status": "stopped",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "slug": slug,
        "internal_port": internal_port,
    })
    return jsonify({"id": project_id, "name": name}), 201


@app.route("/api/projects/<project_id>/slug", methods=["POST"])
@login_required
def api_set_slug(project_id):
    data = request.get_json(force=True, silent=True) or {}
    slug = (data.get("slug") or "").strip().lower()
    if not SLUG_RE.match(slug):
        return jsonify({"error": "Use 2-40 lowercase letters, numbers or dashes"}), 400
    db = get_mongo()
    existing = db.projects.find_one({"slug": slug, "_id": {"$ne": project_id}})
    if existing:
        return jsonify({"error": "That public URL name is already taken"}), 400
    db.projects.update_one({"_id": project_id}, {"$set": {"slug": slug}})
    return jsonify({"ok": True, "slug": slug})


@app.route("/api/projects/<project_id>", methods=["DELETE"])
@login_required
def api_delete_project(project_id):
    _stop_process(project_id)
    shutil.rmtree(project_dir(project_id), ignore_errors=True)
    db = get_mongo()
    db.projects.delete_one({"_id": project_id})
    mongo_delete_all_files(project_id)
    return jsonify({"ok": True})


@app.route("/api/projects/<project_id>/rename", methods=["POST"])
@login_required
def api_rename_project(project_id):
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()[:80]
    if not name:
        return jsonify({"error": "name required"}), 400
    get_mongo().projects.update_one({"_id": project_id}, {"$set": {"name": name}})
    return jsonify({"ok": True})


@app.route("/api/projects/<project_id>/entry", methods=["POST"])
@login_required
def api_set_entry(project_id):
    data = request.get_json(force=True, silent=True) or {}
    entry_file = (data.get("entry_file") or "").strip()
    get_mongo().projects.update_one({"_id": project_id}, {"$set": {"entry_file": entry_file}})
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# API: file browser / editor (MongoDB-backed)
# --------------------------------------------------------------------------

@app.route("/api/projects/<project_id>/files", methods=["GET"])
@login_required
def api_list_files(project_id):
    docs = mongo_list_files(project_id)
    files = sorted(
        [{"path": d["path"], "size": len((d.get("content") or "").encode("utf-8"))} for d in docs],
        key=lambda x: x["path"]
    )
    return jsonify({"files": files})


@app.route("/api/projects/<project_id>/file", methods=["GET"])
@login_required
def api_read_file(project_id):
    rel = request.args.get("path", "")
    content = mongo_read_file(project_id, rel)
    if content is None:
        abort(404)
    return jsonify({"path": rel, "content": content})


@app.route("/api/projects/<project_id>/file", methods=["POST"])
@login_required
def api_write_file(project_id):
    data = request.get_json(force=True, silent=True) or {}
    rel = data.get("path", "")
    content = data.get("content", "")
    if not rel:
        return jsonify({"error": "path required"}), 400
    mongo_save_file(project_id, rel, content)
    target = safe_join(project_dir(project_id), rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/projects/<project_id>/file", methods=["DELETE"])
@login_required
def api_delete_file(project_id):
    rel = request.args.get("path", "")
    mongo_delete_file(project_id, rel)
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
        content = f.read().decode("utf-8", errors="replace")
        mongo_save_file(project_id, rel_path, content)
        target = safe_join(pdir, rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
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

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, tmpdir],
                capture_output=True, text=True, timeout=120,
            )
        except Exception as exc:
            return jsonify({"error": f"clone failed: {exc}"}), 500

        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip() or "git clone failed"}), 400

        mongo_delete_all_files(project_id)
        pdir = project_dir(project_id)
        pdir.mkdir(parents=True, exist_ok=True)

        tmp_path = Path(tmpdir)
        entry_file = None
        for path in sorted(tmp_path.rglob("*")):
            if path.is_dir() or ".git" in path.parts:
                continue
            rel = str(path.relative_to(tmp_path))
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            mongo_save_file(project_id, rel, content)
            target = pdir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            if entry_file is None and path.name in RUN_ENTRY_CANDIDATES:
                entry_file = rel

    db = get_mongo()
    proj = db.projects.find_one({"_id": project_id}, {"slug": 1})
    update_fields = {"github_url": repo_url, "entry_file": entry_file or "main.py"}

    # If the project's slug is still its UUID (never manually set), auto-derive
    # it from the repo name so the public URL becomes human-readable.
    if proj and proj.get("slug") == project_id:
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        slug_base = re.sub(r"[^a-z0-9]+", "-", repo_name.lower()).strip("-")[:40] or project_id
        slug = slug_base
        suffix = 1
        while db.projects.find_one({"slug": slug, "_id": {"$ne": project_id}}):
            slug = f"{slug_base}-{suffix}"
            suffix += 1
        update_fields["slug"] = slug

    db.projects.update_one({"_id": project_id}, {"$set": update_fields})
    return jsonify({"ok": True, "entry_file": entry_file})


# --------------------------------------------------------------------------
# API: environment variables
# --------------------------------------------------------------------------

@app.route("/api/projects/<project_id>/env", methods=["GET"])
@login_required
def api_get_env(project_id):
    proj = get_mongo().projects.find_one({"_id": project_id}, {"env": 1})
    if not proj:
        abort(404)
    return jsonify({"env": proj.get("env", {})})


@app.route("/api/projects/<project_id>/env", methods=["POST"])
@login_required
def api_set_env(project_id):
    data = request.get_json(force=True, silent=True) or {}
    env_vars = data.get("env", {})
    if not isinstance(env_vars, dict):
        return jsonify({"error": "env must be an object"}), 400
    clean = {str(k): str(v) for k, v in env_vars.items() if k}
    get_mongo().projects.update_one({"_id": project_id}, {"$set": {"env": clean}})
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
    except Exception as exc:
        _append_log(project_id, f"[log-reader-error] {exc}")
    finally:
        proc.wait()
        _append_log(project_id, f"[process exited with code {proc.returncode}]")
        with RUNNING_LOCK:
            RUNNING.pop(project_id, None)
        _set_status(project_id, "stopped")


def _set_status(project_id: str, status: str):
    try:
        get_mongo().projects.update_one({"_id": project_id}, {"$set": {"status": status}})
    except Exception:
        pass


def _detect_entry(pdir: Path, configured: str | None) -> str | None:
    if configured and (pdir / configured).exists():
        return configured
    for candidate in RUN_ENTRY_CANDIDATES:
        if (pdir / candidate).exists():
            return candidate
    return None


def _run_project_thread(project_id: str, entry_file: str, env_vars: dict, internal_port: int):
    pdir = project_dir(project_id)
    lp = log_path_for(project_id)
    lp.write_text("")

    _append_log(project_id, "Restoring project files from database ...")
    _restore_project_to_disk(project_id)

    run_env = os.environ.copy()
    run_env.update(env_vars)
    run_env["PYTHONUNBUFFERED"] = "1"
    run_env["PORT"] = str(internal_port)
    run_env["HOST"] = "0.0.0.0"

    requirements = pdir / "requirements.txt"
    if requirements.exists():
        _append_log(project_id, "Installing dependencies from requirements.txt ...")
        install = subprocess.run(
            ["pip", "install", "--no-input", "-r", str(requirements)],
            cwd=str(pdir), capture_output=True, text=True, env=run_env,
        )
        for line in (install.stdout + install.stderr).splitlines():
            _append_log(project_id, line)
        if install.returncode != 0:
            _append_log(project_id, "[dependency install failed — attempting to run anyway]")

    package_json = pdir / "package.json"
    if entry_file.endswith(".js") and package_json.exists():
        _append_log(project_id, "Installing npm dependencies ...")
        npm_install = subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund"],
            cwd=str(pdir), capture_output=True, text=True, env=run_env,
        )
        for line in (npm_install.stdout + npm_install.stderr).splitlines():
            _append_log(project_id, line)

    cmd = ["node", entry_file] if entry_file.endswith(".js") else ["python3", entry_file]
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

    db = get_mongo()
    proj = db.projects.find_one({"_id": project_id})
    if not proj:
        abort(404)

    pdir = project_dir(project_id)
    pdir.mkdir(parents=True, exist_ok=True)
    entry_file = _detect_entry(pdir, proj.get("entry_file"))
    if not entry_file:
        docs = mongo_list_files(project_id)
        paths = [d["path"] for d in docs]
        for candidate in RUN_ENTRY_CANDIDATES:
            if candidate in paths:
                entry_file = candidate
                break
    if not entry_file:
        return jsonify({"error": "No entry file found"}), 400

    env_vars = proj.get("env", {})
    internal_port = proj.get("internal_port") or _next_free_port()

    thread = threading.Thread(
        target=_run_project_thread,
        args=(project_id, entry_file, env_vars, internal_port),
        daemon=True,
    )
    thread.start()
    time.sleep(0.3)
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


@app.route("/api/projects/<project_id>/logs/clear", methods=["POST"])
@login_required
def api_clear_logs(project_id):
    lp = log_path_for(project_id)
    if lp.exists():
        lp.write_text("")
    return jsonify({"ok": True})


@app.route("/api/projects/<project_id>/status", methods=["GET"])
@login_required
def api_get_status(project_id):
    return jsonify({"running": project_id in RUNNING})


@app.route("/api/ping-config", methods=["GET"])
@login_required
def api_ping_config():
    return jsonify({
        "ping_url": PING_URL,
        "ping_interval": PING_INTERVAL,
        "enabled": bool(PING_URL),
    })


# --------------------------------------------------------------------------
# ZIP download
# --------------------------------------------------------------------------

@app.route("/api/projects/<project_id>/download")
@login_required
def api_download_project(project_id):
    db = get_mongo()
    proj = db.projects.find_one({"_id": project_id}, {"name": 1})
    name = ((proj["name"] if proj else project_id) or project_id).replace(" ", "_")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc in mongo_list_files(project_id):
            zf.writestr(doc["path"], doc.get("content", ""))
    buf.seek(0)
    return send_file(
        buf, mimetype="application/zip", as_attachment=True,
        download_name=f"{name}.zip",
    )


# --------------------------------------------------------------------------
# Public URL proxy — with HTML URL-rewriting shim injection
# --------------------------------------------------------------------------

HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding", "content-length",
}

# JS shim template: rewrites absolute-path fetch/XHR calls so bot admin panels work
_PROXY_SHIM_TPL = """<script>
(function(){{
  var B='{base}';
  var _f=window.fetch;
  window.fetch=function(u,o){{
    if(typeof u==='string'&&u.startsWith('/')&&!u.startsWith(B)&&!u.startsWith('//')){{\
u=B+u;}}
    return _f.call(this,u,o);
  }};
  var _xo=XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open=function(m,u){{
    if(typeof u==='string'&&u.startsWith('/')&&!u.startsWith(B)&&!u.startsWith('//')){{\
u=B+u;}}
    return _xo.apply(this,arguments);
  }};
}})();
</script>"""


def _inject_proxy_shim(html: str, ident: str) -> str:
    """Inject <base href> and a fetch/XHR URL-rewriting shim into an HTML page."""
    base = f"/pub/{ident}"
    base_tag = f'<base href="{base}/">'
    shim = _PROXY_SHIM_TPL.format(base=base)
    inject = base_tag + shim
    # Try to inject right after <head>
    for tag in ("<head>", "<Head>", "<HEAD>"):
        if tag in html:
            return html.replace(tag, tag + inject, 1)
    # Fallback: inject before </head>
    for tag in ("</head>", "</Head>", "</HEAD>"):
        if tag in html:
            return html.replace(tag, inject + tag, 1)
    # Last resort: prepend
    return inject + html


def _find_project_by_ident(ident: str):
    db = get_mongo()
    proj = db.projects.find_one({"$or": [{"slug": ident}, {"_id": ident}]})
    if proj:
        proj["id"] = proj.pop("_id")
    return proj


def _proc_alive(project_id: str) -> bool:
    """Return True if the process is in RUNNING and still alive."""
    with RUNNING_LOCK:
        entry = RUNNING.get(project_id)
    if not entry:
        return False
    proc = entry.get("proc")
    return proc is not None and proc.poll() is None


def _proxy_request(project, subpath, ident):
    pid = project["id"]

    if pid not in RUNNING:
        return Response(
            "⚠️  This project isn't running right now.\n"
            "Open it in CodeHost and hit ▶ Run, then reload this URL.",
            status=503, mimetype="text/plain",
        )

    port = project["internal_port"]
    target_url = f"http://127.0.0.1:{port}/{subpath}"
    if request.query_string:
        target_url += "?" + request.query_string.decode("utf-8")

    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}

    # Retry a few times to handle slow startup (pip install, Telethon init, etc.)
    last_conn_err = None
    for attempt in range(4):
        try:
            upstream = requests.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=request.get_data(),
                cookies=request.cookies,
                allow_redirects=False,
                timeout=30,
            )
            last_conn_err = None
            break
        except requests.exceptions.ConnectionError as exc:
            last_conn_err = exc
            if attempt < 3:
                time.sleep(2)
        except requests.exceptions.Timeout:
            return Response("⚠️  Upstream project timed out.", status=504, mimetype="text/plain")

    if last_conn_err is not None:
        # Check whether the process crashed (already exited) or is still starting
        if not _proc_alive(pid):
            return Response(
                "⚠️  Project process crashed during startup — check the logs.\n\n"
                "Most common causes:\n"
                "  • Missing environment variables (API_ID, API_HASH, API_KEY, etc.)\n"
                "    → Open CodeHost → your project → Env tab → add the required vars → re-run.\n"
                "  • Syntax error or missing dependency in your code.\n"
                "    → Check the Logs panel in CodeHost for the full error traceback.\n",
                status=502, mimetype="text/plain",
            )
        return Response(
            "⚠️  Project is still starting up — port not accepting connections yet.\n"
            "Wait a few seconds and reload this page.\n\n"
            "If this persists, check the Logs panel in CodeHost for errors.",
            status=502, mimetype="text/plain",
        )

    content_type = upstream.headers.get("content-type", "")
    response_headers = [
        (k, v) for k, v in upstream.raw.headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS
    ]

    # Inject shim into HTML responses so bot admin panels work correctly
    if "text/html" in content_type:
        try:
            html = upstream.content.decode(upstream.encoding or "utf-8", errors="replace")
            html = _inject_proxy_shim(html, ident)
            return Response(html, status=upstream.status_code, headers=response_headers,
                            content_type="text/html; charset=utf-8")
        except Exception:
            pass

    return Response(upstream.content, status=upstream.status_code, headers=response_headers)


def _proxy_not_found(ident: str):
    """Helpful 404 instead of a blank Flask error page."""
    host = request.host_url.rstrip("/")
    body = (
        f"⚠️  No project found at /pub/{ident}/\n\n"
        f"Possible reasons:\n"
        f"  1. URL name not set yet.\n"
        f"     → Open CodeHost admin → your project → Settings\n"
        f"       → set 'Public URL name' to '{ident}' and click Set.\n\n"
        f"  2. Project created before auto-slug was added (URL uses UUID).\n"
        f"     → Go to {host}/admin → open your project\n"
        f"       → the correct URL is shown in the URL bar at the top.\n\n"
        f"  3. Typo in the URL — double-check spelling.\n"
    )
    return Response(body, status=404, mimetype="text/plain")


@app.route("/pub/<ident>/", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def public_proxy_root(ident):
    project = _find_project_by_ident(ident)
    if not project:
        return _proxy_not_found(ident)
    return _proxy_request(project, "", ident)


@app.route("/pub/<ident>/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def public_proxy(ident, subpath):
    project = _find_project_by_ident(ident)
    if not project:
        return _proxy_not_found(ident)
    return _proxy_request(project, subpath, ident)


# --------------------------------------------------------------------------
# Health endpoints
# --------------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})


@app.route("/ping")
def ping():
    return jsonify({"pong": True, "time": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

# CodeHost

A small self-hosted admin panel for running your own bots and APIs (Python or Node)
from the browser — edit code, import from GitHub, set environment variables, run/stop
the process, watch live logs, and download the project as a ZIP.

Everything lives in one Flask app (`app.py`). No external database required — it
uses SQLite and stores each project as a plain folder on disk.

## Files

- `app.py` — the entire backend (routes, process runner, GitHub import, ZIP export)
- `templates/` — the 3 HTML pages (login, dashboard, project editor)
- `static/` — CSS + the editor/terminal JS
- `requirements.txt` — Python dependencies
- `Procfile` — process command for Render/Heroku-style platforms
- `Dockerfile` — container build (works on Render, Railway, Fly.io, etc.)
- `render.yaml` — one-click Render "Blueprint" config

## 1. Deploy to Render (recommended, easiest)

1. Push this folder to a **new GitHub repository**.
2. Go to [render.com](https://render.com) → **New +** → **Blueprint**, and point it at
   your repo. Render will read `render.yaml` automatically.
   - If you'd rather not use a Blueprint, create a **Web Service** manually instead:
     - Build command: `pip install -r requirements.txt`
     - Start command: `gunicorn app:app --workers 1 --threads 4 --bind 0.0.0.0:$PORT --timeout 120`
3. Set the environment variables when prompted (or under **Environment** later):
   - `ADMIN_KEY` — the password you'll use to log in. Pick something long and random.
   - `SECRET_KEY` — Render can auto-generate this (the blueprint already does).
4. Add a **persistent disk** mounted at `/app/data` (the blueprint already requests a
   1GB disk). Without a disk, everything you create gets wiped every time Render
   restarts/redeploys the service — your projects, files and env vars live there.
5. Deploy. Render gives you a public URL like `https://codehost.onrender.com` —
   that's your CodeHost instance. Open it, log in with your `ADMIN_KEY`.

## 2. Deploy with Docker (Render, Railway, Fly.io, your own VPS, etc.)

```bash
docker build -t codehost .
docker run -p 10000:10000 \
  -e ADMIN_KEY=your-secret-key \
  -e SECRET_KEY=some-random-string \
  -v $(pwd)/data:/app/data \
  codehost
```

The `-v` volume mount is what makes your projects persist across container restarts.

## 3. Run locally

```bash
pip install -r requirements.txt
export ADMIN_KEY=changeme
export SECRET_KEY=dev-secret
python app.py
```

Visit `http://localhost:5000` and log in with your `ADMIN_KEY`.

## Using it

1. **Log in** with the admin key you set in `ADMIN_KEY`.
2. **Create a project** from the dashboard, or **import a GitHub repo** from inside a
   project (paste a `https://github.com/user/repo.git` URL — it clones the repo's
   files straight in).
3. **Edit files** in the built-in code editor. `Ctrl+S` saves.
4. **Set environment variables** for the project — these get injected into the process
   when it runs (great for bot tokens, API keys, etc.) and are written to a local
   `.env` file that's excluded from ZIP downloads and GitHub imports.
5. Set the **entry file** if it's not auto-detected (it looks for `main.py`, `bot.py`,
   `app.py`, `run.py`, `server.py`, or `index.js` by default).
6. Hit **Run**. If a `requirements.txt` (Python) or `package.json` (Node) is present,
   dependencies install automatically before the process starts. Logs stream live in
   the terminal panel at the bottom.
7. Hit **Stop** anytime, or **Download ZIP** to grab the whole project.

## Notes & limits

- This app keeps running-process state in memory, so it must run with a **single
  worker** (`--workers 1`). The Procfile/Dockerfile/render.yaml already do this. If you
  scale to multiple instances, running processes won't be visible from every instance.
- Change `ADMIN_KEY` and `SECRET_KEY` before deploying anywhere public — the defaults
  in `app.py` are placeholders only.
- On Render's free plan, the service can spin down when idle; the next request wakes
  it back up (and any process you had running will need to be started again).
- Attach a persistent disk (or a volume, outside of Render) if you want projects to
  survive restarts/redeploys — without one, `data/` is ephemeral.

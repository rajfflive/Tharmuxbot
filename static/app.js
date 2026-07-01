/* CodeHost — Project Page Logic */
(function () {
  const workspace = document.querySelector(".workspace");
  if (!workspace) return; // dashboard page

  const projectId = workspace.dataset.projectId;

  // ── Elements ──────────────────────────────────────────────────────────────
  const fileListEl       = document.getElementById("file-list");
  const fileListEmpty    = document.getElementById("file-list-empty");
  const terminal         = document.getElementById("terminal-output");
  const editor           = document.getElementById("code-editor");
  const currentFileLbl   = document.getElementById("current-file-label");
  const unsavedBadge     = document.getElementById("unsaved-badge");
  const saveStatus       = document.getElementById("save-status");
  const saveBtn          = document.getElementById("save-btn");
  const backToLogsBtn    = document.getElementById("back-to-logs-btn");
  const logsView         = document.getElementById("logs-view");
  const editorView       = document.getElementById("editor-view");
  const runBtn           = document.getElementById("run-btn");
  const stopBtn          = document.getElementById("stop-btn");
  const runDot           = document.getElementById("run-dot");
  const newFileBtn       = document.getElementById("new-file-btn");
  const uploadInput      = document.getElementById("upload-input");
  const githubUrlInput   = document.getElementById("github-url");
  const githubImportBtn  = document.getElementById("github-import-btn");
  const envListEl        = document.getElementById("env-list");
  const envKeyInput      = document.getElementById("env-key");
  const envValueInput    = document.getElementById("env-value");
  const envAddBtn        = document.getElementById("env-add-btn");
  const envSaveBtn       = document.getElementById("env-save-btn");
  const entryFileInput   = document.getElementById("entry-file");
  const entrySaveBtn     = document.getElementById("entry-save-btn");
  const publicUrlInput   = document.getElementById("public-url-input");
  const copyUrlBtn       = document.getElementById("copy-url-btn");
  const openUrlBtn       = document.getElementById("open-url-btn");
  const slugInput        = document.getElementById("slug-input");
  const slugSaveBtn      = document.getElementById("slug-save-btn");
  const errorsToggle     = document.getElementById("errors-only-toggle");
  const autoscrollToggle = document.getElementById("autoscroll-toggle");
  const clearLogsBtn     = document.getElementById("clear-logs-btn");
  const deleteProjectBtn = document.getElementById("delete-project-btn");
  const pingStatus       = document.getElementById("ping-status");
  const logCount         = document.getElementById("log-count");
  const toastContainer   = document.getElementById("toast-container");

  // ── State ─────────────────────────────────────────────────────────────────
  let currentFile  = null;
  let dirty        = false;
  let envVars      = {};
  let lastRawLog   = "";
  let logLines     = 0;
  let logsCleared  = false;
  let isRunning    = false;

  // ── Sidebar tab navigation ────────────────────────────────────────────────
  document.querySelectorAll(".sidenav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".sidenav-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("panel-" + btn.dataset.panel).classList.add("active");
    });
  });

  // ── Helpers ───────────────────────────────────────────────────────────────
  function api(path, opts) {
    return fetch(`/api/projects/${projectId}${path}`, opts).then((res) => {
      if (res.status === 401) {
        toast("Session expired — redirecting to login", "err");
        setTimeout(() => (window.location.href = "/login"), 1400);
        throw new Error("unauthorized");
      }
      return res;
    });
  }

  function toast(msg, type) {
    const el = document.createElement("div");
    el.className = `toast ${type || ""}`;
    el.textContent = msg;
    toastContainer.appendChild(el);
    setTimeout(() => el.remove(), 3600);
  }

  function setDirty(v) {
    dirty = v;
    unsavedBadge.classList.toggle("hidden", !v);
  }

  function flashSave(msg, isErr) {
    saveStatus.textContent = msg;
    saveStatus.className = "save-status show" + (isErr ? " err" : "");
    setTimeout(() => saveStatus.classList.remove("show"), 2200);
  }

  // ── View switching ────────────────────────────────────────────────────────
  function showEditorView(path) {
    logsView.classList.remove("active");
    editorView.classList.add("active");
    currentFileLbl.textContent = path;
    setDirty(false);
  }

  function showLogsView() {
    editorView.classList.remove("active");
    logsView.classList.add("active");
    currentFile = null;
    currentFileLbl.textContent = "—";
    editor.value = "";
    setDirty(false);
    highlightFile(null);
  }

  backToLogsBtn.addEventListener("click", () => {
    if (dirty && !confirm("Unsaved changes — close anyway?")) return;
    showLogsView();
  });

  // ── File list ─────────────────────────────────────────────────────────────
  function highlightFile(path) {
    fileListEl.querySelectorAll("li").forEach((li) => {
      li.classList.toggle("active", li.dataset.path === path);
    });
  }

  async function loadFiles() {
    const res = await api("/files");
    const { files } = await res.json();
    fileListEl.innerHTML = "";
    fileListEmpty.style.display = files.length ? "none" : "block";

    files.forEach(({ path, size }) => {
      const li = document.createElement("li");
      li.dataset.path = path;
      if (path === currentFile) li.classList.add("active");

      const icon = document.createElement("span");
      icon.className = "file-icon";
      icon.textContent = iconFor(path);

      const name = document.createElement("span");
      name.className = "file-name";
      name.textContent = path;
      name.title = `${path}  (${fmtSize(size)})`;

      const del = document.createElement("button");
      del.className = "file-del";
      del.textContent = "✕";
      del.title = "Delete";
      del.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete "${path}"?`)) return;
        await api(`/file?path=${encodeURIComponent(path)}`, { method: "DELETE" });
        if (currentFile === path) showLogsView();
        loadFiles();
        toast(`Deleted ${path}`, "warn");
      });

      li.addEventListener("click", () => openFile(path));
      li.append(icon, name, del);
      fileListEl.appendChild(li);
    });
  }

  function iconFor(path) {
    const ext = path.split(".").pop().toLowerCase();
    return { py: "🐍", js: "📜", json: "📋", md: "📝", txt: "📄",
             html: "🌐", css: "🎨", sh: "⚙️", yml: "⚙️", yaml: "⚙️",
             env: "🔑", toml: "⚙️" }[ext] || "📄";
  }

  function fmtSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  async function openFile(path) {
    try {
      const res = await api(`/file?path=${encodeURIComponent(path)}`);
      if (!res.ok) { toast("Could not open " + path, "err"); return; }
      const { content } = await res.json();
      currentFile = path;
      editor.value = content;
      showEditorView(path);
      highlightFile(path);
      // Switch sidebar to files panel so user sees the list
      document.querySelector('[data-panel="files"]').click();
      editor.focus();
    } catch (_) {}
  }

  async function saveCurrentFile() {
    if (!currentFile) { flashSave("No file open", true); return; }
    try {
      const res = await api("/file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: currentFile, content: editor.value }),
      });
      if (!res.ok) {
        const { error } = await res.json().catch(() => ({}));
        flashSave("Save failed: " + (error || res.status), true);
        return;
      }
      setDirty(false);
      flashSave("Saved ✓");
    } catch (_) {
      flashSave("Save failed — check connection", true);
    }
  }

  editor.addEventListener("input", () => setDirty(true));
  editor.addEventListener("keydown", (e) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const s = editor.selectionStart, end = editor.selectionEnd;
      editor.value = editor.value.slice(0, s) + "    " + editor.value.slice(end);
      editor.selectionStart = editor.selectionEnd = s + 4;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); saveCurrentFile(); }
  });
  saveBtn.addEventListener("click", saveCurrentFile);

  // ── New file / upload ────────────────────────────────────────────────────
  newFileBtn.addEventListener("click", async () => {
    const name = prompt("File name (e.g. main.py):");
    if (!name) return;
    await api("/file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: name, content: "" }),
    });
    await loadFiles();
    openFile(name);
  });

  uploadInput.addEventListener("change", async () => {
    if (!uploadInput.files.length) return;
    const fd = new FormData();
    for (const f of uploadInput.files) fd.append("files", f, f.name);
    const res = await api("/upload", { method: "POST", body: fd });
    uploadInput.value = "";
    if (res.ok) { toast("Files uploaded ✓", "ok"); loadFiles(); }
    else toast("Upload failed", "err");
  });

  // ── GitHub import ─────────────────────────────────────────────────────────
  if (githubImportBtn) {
    githubImportBtn.addEventListener("click", async () => {
      const url = (githubUrlInput.value || "").trim();
      if (!url) return;
      const orig = githubImportBtn.textContent;
      githubImportBtn.textContent = "Importing…";
      githubImportBtn.disabled = true;
      try {
        const res = await api("/github", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repo_url: url }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast("Import failed: " + (data.error || "unknown"), "err"); return; }
        toast("Repo imported ✓", "ok");
        currentFile = null;
        showLogsView();
        loadFiles();
      } finally {
        githubImportBtn.textContent = orig;
        githubImportBtn.disabled = false;
      }
    });
  }

  // ── Env vars ─────────────────────────────────────────────────────────────
  function renderEnv() {
    envListEl.innerHTML = "";
    const entries = Object.entries(envVars);
    if (!entries.length) {
      envListEl.innerHTML = '<div style="padding:12px;color:var(--t3);font-size:12px;text-align:center">No variables yet</div>';
      return;
    }
    entries.forEach(([k, v]) => {
      const row = document.createElement("div");
      row.className = "env-item";

      const key = document.createElement("span");
      key.className = "env-item-key";
      key.textContent = k;
      key.title = k;

      const val = document.createElement("span");
      val.className = "env-item-val";
      val.textContent = v.length > 28 ? v.slice(0, 28) + "…" : v;
      val.title = v;

      const btn = document.createElement("button");
      btn.className = "env-del-btn";
      btn.textContent = "✕";
      btn.title = "Remove";
      btn.addEventListener("click", () => { delete envVars[k]; renderEnv(); });

      row.append(key, val, btn);
      envListEl.appendChild(row);
    });
  }

  async function loadEnv() {
    const res = await api("/env");
    const { env } = await res.json();
    envVars = env || {};
    renderEnv();
  }

  async function saveEnv() {
    const res = await api("/env", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ env: envVars }),
    });
    if (res.ok) toast("Env vars saved to MongoDB ✓", "ok");
    else toast("Could not save env vars", "err");
  }

  envAddBtn.addEventListener("click", () => {
    const k = envKeyInput.value.trim();
    const v = envValueInput.value;
    if (!k) { envKeyInput.focus(); return; }
    envVars[k] = v;
    envKeyInput.value = "";
    envValueInput.value = "";
    renderEnv();
  });

  envValueInput.addEventListener("keydown", (e) => { if (e.key === "Enter") envAddBtn.click(); });
  if (envSaveBtn) envSaveBtn.addEventListener("click", saveEnv);

  // ── Settings ──────────────────────────────────────────────────────────────
  if (entrySaveBtn) {
    entrySaveBtn.addEventListener("click", async () => {
      const res = await api("/entry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entry_file: entryFileInput.value.trim() }),
      });
      toast(res.ok ? "Entry file saved ✓" : "Could not save entry file", res.ok ? "ok" : "err");
    });
  }

  if (slugSaveBtn) {
    slugSaveBtn.addEventListener("click", async () => {
      const slug = slugInput.value.trim().toLowerCase();
      if (!slug) return;
      const res = await api("/slug", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { toast(data.error || "Could not set URL name", "err"); return; }
      toast("Public URL updated ✓", "ok");
      const newUrl = publicUrlInput.value.replace(/\/pub\/[^/]+\//, `/pub/${data.slug}/`);
      publicUrlInput.value = newUrl;
      if (openUrlBtn) openUrlBtn.href = newUrl;
    });
  }

  if (copyUrlBtn) {
    copyUrlBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(publicUrlInput.value);
        toast("URL copied!", "ok");
      } catch (_) {
        publicUrlInput.select();
        toast("Select the URL manually", "warn");
      }
    });
  }

  if (deleteProjectBtn) {
    deleteProjectBtn.addEventListener("click", async () => {
      if (!confirm("Delete this entire project? This CANNOT be undone.")) return;
      const res = await fetch(`/api/projects/${projectId}`, { method: "DELETE" });
      if (res.ok) window.location.href = "/";
      else toast("Could not delete project", "err");
    });
  }

  // ── Run / Stop ────────────────────────────────────────────────────────────
  function setRunUI(running) {
    isRunning = running;
    runDot.classList.toggle("active", running);
    runBtn.disabled = running;
    stopBtn.disabled = !running;
  }

  runBtn.addEventListener("click", async () => {
    const orig = runBtn.innerHTML;
    runBtn.disabled = true;
    runBtn.textContent = "Starting…";
    terminal.textContent = "";
    logsCleared = false;
    lastRawLog = "";
    try {
      const res = await api("/run", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast("Run failed: " + (data.error || "unknown error"), "err");
        runBtn.disabled = false;
        return;
      }
      setRunUI(true);
      toast("Project started ✓", "ok");
      // Switch to logs view
      if (editorView.classList.contains("active")) {
        // stay in editor — logs poll in background
      }
    } finally {
      runBtn.innerHTML = orig;
    }
  });

  stopBtn.addEventListener("click", async () => {
    stopBtn.disabled = true;
    stopBtn.textContent = "Stopping…";
    const res = await api("/stop", { method: "POST" });
    stopBtn.textContent = "Stop";
    if (res.ok) { setRunUI(false); toast("Project stopped", "ok"); }
    else stopBtn.disabled = false;
  });

  // ── Logs ─────────────────────────────────────────────────────────────────
  clearLogsBtn.addEventListener("click", async () => {
    logsCleared = true;
    lastRawLog = "";
    terminal.innerHTML = "";
    logLines = 0;
    if (logCount) logCount.textContent = "";
    await api("/logs/clear", { method: "POST" }).catch(() => {});
  });

  function lineClass(line) {
    const l = line.toLowerCase();
    if (l.includes("error") || l.includes("exception") || l.includes("traceback") || l.includes("failed")) return "log-err";
    if (l.includes("warn")) return "log-warn";
    if (line.startsWith("[") && (l.includes("starting:") || l.includes("process exited") ||
        l.includes("installing") || l.includes("restoring"))) return "log-sys";
    if (l.includes("success") || l.includes("started") || l.includes("running")) return "log-ok";
    return "";
  }

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderLogs(raw) {
    if (logsCleared) return;
    const lines = raw.split("\n").filter(Boolean);
    logLines = lines.length;
    if (logCount) logCount.textContent = lines.length > 0 ? `${lines.length} lines` : "";

    const errOnly = errorsToggle.checked;
    const shown = errOnly
      ? lines.filter((l) => { const c = lineClass(l); return c === "log-err" || c === "log-warn"; })
      : lines;

    if (!shown.length) {
      terminal.innerHTML = '<span class="log-muted">No logs yet — hit ▶ Run to start the project.</span>';
      return;
    }

    const atBottom = terminal.scrollTop + terminal.clientHeight >= terminal.scrollHeight - 40;
    terminal.innerHTML = shown
      .map((l) => `<span class="log-line ${lineClass(l)}">${esc(l)}</span>`)
      .join("\n");

    if (autoscrollToggle.checked && atBottom) {
      terminal.scrollTop = terminal.scrollHeight;
    }
  }

  errorsToggle.addEventListener("change", () => renderLogs(lastRawLog));

  async function pollLogs() {
    try {
      const res = await api("/logs");
      if (res.ok) {
        const { log, running } = await res.json();
        const raw = log || "";
        if (raw !== lastRawLog) { lastRawLog = raw; renderLogs(raw); }
        setRunUI(running);
      }
    } catch (_) { /* transient — ignore */ }
    setTimeout(pollLogs, 2000);
  }

  // ── Ping status ───────────────────────────────────────────────────────────
  async function checkPing() {
    try {
      const res = await fetch("/api/ping-config");
      if (!res.ok) return;
      const { enabled, ping_interval, ping_url } = await res.json();
      if (pingStatus) {
        if (enabled) {
          pingStatus.textContent = `● ping on (${Math.round(ping_interval / 60)}min)`;
          pingStatus.className = "ping-pill on";
          pingStatus.title = `Pinging: ${ping_url}`;
        } else {
          pingStatus.textContent = "● ping off";
          pingStatus.className = "ping-pill";
          pingStatus.title = "Set RENDER_EXTERNAL_URL env var to enable auto-ping";
        }
      }
    } catch (_) {}
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  loadFiles();
  loadEnv();
  renderLogs("");
  pollLogs();
  checkPing();
})();

/* ════════════════════════════════════════════════
   DASHBOARD — new project button
════════════════════════════════════════════════ */
(function () {
  const btn = document.getElementById("new-project-btn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const name = prompt("Project name:", "My Bot");
    if (!name) return;
    const res = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (res.ok) {
      const data = await res.json();
      window.location.href = "/projects/" + data.id;
    } else {
      alert("Could not create project.");
    }
  });
})();

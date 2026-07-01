(function () {
  const layout = document.querySelector(".project-layout");
  if (!layout) return;

  const projectId = layout.dataset.projectId;
  const fileListEl = document.getElementById("file-list");
  const editor = document.getElementById("code-editor");
  const currentFileLabel = document.getElementById("current-file-label");
  const unsavedDot = document.getElementById("unsaved-dot");
  const saveStatus = document.getElementById("save-status");
  const saveBtn = document.getElementById("save-btn");
  const closeFileBtn = document.getElementById("close-file-btn");
  const terminalOutput = document.getElementById("terminal-output");
  const runBtn = document.getElementById("run-btn");
  const stopBtn = document.getElementById("stop-btn");
  const runStatus = document.getElementById("run-status");
  const newFileBtn = document.getElementById("new-file-btn");
  const uploadInput = document.getElementById("upload-input");
  const githubUrlInput = document.getElementById("github-url");
  const githubImportBtn = document.getElementById("github-import-btn");
  const envList = document.getElementById("env-list");
  const envKeyInput = document.getElementById("env-key");
  const envValueInput = document.getElementById("env-value");
  const envAddBtn = document.getElementById("env-add-btn");
  const envSaveBtn = document.getElementById("env-save-btn");
  const entryFileInput = document.getElementById("entry-file");
  const entrySaveBtn = document.getElementById("entry-save-btn");
  const publicUrlInput = document.getElementById("public-url-input");
  const copyUrlBtn = document.getElementById("copy-url-btn");
  const slugInput = document.getElementById("slug-input");
  const slugSaveBtn = document.getElementById("slug-save-btn");
  const errorsOnlyToggle = document.getElementById("errors-only-toggle");
  const autoscrollToggle = document.getElementById("autoscroll-toggle");
  const clearLogsBtn = document.getElementById("clear-logs-btn");
  const toastContainer = document.getElementById("toast-container");
  const deleteProjectBtn = document.getElementById("delete-project-btn");
  const pingBadge = document.getElementById("ping-badge");

  let currentFile = null;
  let dirty = false;
  let envVars = {};
  let lastRawLog = "";
  let logsCleared = false;

  // ---- Sidebar tabs ----
  document.querySelectorAll(".stab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".stab").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".stab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      document.getElementById("tab-" + tab).classList.add("active");
    });
  });

  // ---- Utils ----
  function apiUrl(path) {
    return `/api/projects/${projectId}${path}`;
  }

  function showToast(message, type) {
    const el = document.createElement("div");
    el.className = "toast " + (type || "");
    el.textContent = message;
    toastContainer.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  async function apiFetch(path, options) {
    try {
      const res = await fetch(apiUrl(path), options);
      if (res.status === 401) {
        showToast("Session expired — please log in again.", "error");
        setTimeout(() => (window.location.href = "/login"), 1200);
        throw new Error("unauthorized");
      }
      return res;
    } catch (err) {
      if (err.message === "unauthorized") throw err;
      showToast("Network error — check your connection.", "error");
      throw err;
    }
  }

  function setDirty(value) {
    dirty = value;
    unsavedDot.classList.toggle("hidden", !dirty);
  }

  function flashSaveStatus(message, isError) {
    saveStatus.textContent = message;
    saveStatus.classList.toggle("error", !!isError);
    saveStatus.classList.add("show");
    setTimeout(() => saveStatus.classList.remove("show"), 2000);
  }

  // ---- File list ----
  async function loadFiles(selectFirst) {
    const res = await apiFetch("/files");
    const data = await res.json();
    fileListEl.innerHTML = "";
    data.files.forEach((f) => {
      const li = document.createElement("li");
      li.className = f.path === currentFile ? "active" : "";
      const label = document.createElement("span");
      label.textContent = f.path;
      label.style.flex = "1";
      label.addEventListener("click", () => openFile(f.path));
      const del = document.createElement("span");
      del.textContent = "✕";
      del.className = "file-delete";
      del.title = "Delete file";
      del.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete ${f.path}?`)) return;
        await apiFetch(`/file?path=${encodeURIComponent(f.path)}`, { method: "DELETE" });
        if (currentFile === f.path) closeFile();
        loadFiles(false);
      });
      li.appendChild(label);
      li.appendChild(del);
      fileListEl.appendChild(li);
    });
    if (selectFirst && data.files.length && !currentFile) {
      openFile(data.files[0].path);
    }
  }

  async function openFile(path) {
    const res = await apiFetch(`/file?path=${encodeURIComponent(path)}`);
    if (!res.ok) { showToast("Could not open " + path, "error"); return; }
    const data = await res.json();
    currentFile = path;
    editor.value = data.content;
    currentFileLabel.textContent = path;
    closeFileBtn.style.display = "inline-flex";
    setDirty(false);
    loadFiles(false);
  }

  function closeFile() {
    currentFile = null;
    editor.value = "";
    currentFileLabel.textContent = "No file open";
    closeFileBtn.style.display = "none";
    setDirty(false);
    loadFiles(false);
  }

  closeFileBtn.addEventListener("click", () => {
    if (dirty && !confirm("You have unsaved changes. Close anyway?")) return;
    closeFile();
  });

  async function saveCurrentFile() {
    if (!currentFile) { flashSaveStatus("Open a file first", true); return; }
    try {
      const res = await apiFetch("/file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: currentFile, content: editor.value }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        flashSaveStatus("Save failed: " + (err.error || res.status), true);
        return;
      }
      setDirty(false);
      flashSaveStatus("Saved ✓", false);
    } catch (_e) {
      flashSaveStatus("Save failed — check connection", true);
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

  newFileBtn.addEventListener("click", async () => {
    const name = prompt("File name (e.g. main.py):");
    if (!name) return;
    await apiFetch("/file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: name, content: "" }),
    });
    await loadFiles(false);
    openFile(name);
  });

  uploadInput.addEventListener("change", async () => {
    if (!uploadInput.files.length) return;
    const formData = new FormData();
    for (const file of uploadInput.files) formData.append("files", file, file.name);
    await apiFetch("/upload", { method: "POST", body: formData });
    uploadInput.value = "";
    showToast("Files uploaded", "success");
    loadFiles(false);
  });

  // ---- GitHub import ----
  if (githubImportBtn) {
    githubImportBtn.addEventListener("click", async () => {
      const url = githubUrlInput.value.trim();
      if (!url) return;
      githubImportBtn.textContent = "Importing...";
      githubImportBtn.disabled = true;
      try {
        const res = await apiFetch("/github", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repo_url: url }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          showToast("Import failed: " + (err.error || "unknown error"), "error");
          return;
        }
        showToast("Repo imported successfully!", "success");
        currentFile = null;
        closeFile();
        await loadFiles(true);
      } finally {
        githubImportBtn.textContent = "Import repo";
        githubImportBtn.disabled = false;
      }
    });
  }

  // ---- Environment Variables ----
  function renderEnvList() {
    envList.innerHTML = "";
    const entries = Object.entries(envVars);
    if (!entries.length) {
      envList.innerHTML = '<div class="env-empty">No env vars yet.</div>';
      return;
    }
    entries.forEach(([key, value]) => {
      const row = document.createElement("div");
      row.className = "env-item";
      const keyEl = document.createElement("span");
      keyEl.className = "env-key";
      keyEl.textContent = key;
      const valEl = document.createElement("span");
      valEl.className = "env-val";
      valEl.textContent = value.length > 30 ? value.slice(0, 30) + "…" : value;
      valEl.title = value;
      const remove = document.createElement("button");
      remove.textContent = "✕";
      remove.className = "env-remove btn small danger";
      remove.addEventListener("click", () => { delete envVars[key]; renderEnvList(); });
      row.appendChild(keyEl);
      row.appendChild(valEl);
      row.appendChild(remove);
      envList.appendChild(row);
    });
  }

  async function loadEnv() {
    const res = await apiFetch("/env");
    const data = await res.json();
    envVars = data.env || {};
    renderEnvList();
  }

  async function saveEnv() {
    const res = await apiFetch("/env", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ env: envVars }),
    });
    showToast(res.ok ? "Env vars saved to MongoDB ✓" : "Could not save env vars", res.ok ? "success" : "error");
    renderEnvList();
  }

  envAddBtn.addEventListener("click", () => {
    const key = envKeyInput.value.trim();
    const value = envValueInput.value;
    if (!key) return;
    envVars[key] = value;
    envKeyInput.value = "";
    envValueInput.value = "";
    renderEnvList();
  });

  envValueInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") envAddBtn.click();
  });

  if (envSaveBtn) envSaveBtn.addEventListener("click", saveEnv);

  // ---- Entry file / slug ----
  if (entrySaveBtn) {
    entrySaveBtn.addEventListener("click", async () => {
      const res = await apiFetch("/entry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entry_file: entryFileInput.value.trim() }),
      });
      showToast(res.ok ? "Entry file saved ✓" : "Could not save entry file", res.ok ? "success" : "error");
    });
  }

  if (copyUrlBtn) {
    copyUrlBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(publicUrlInput.value);
        showToast("URL copied!", "success");
      } catch (_e) {
        publicUrlInput.select();
        showToast("Select and copy manually", "error");
      }
    });
  }

  if (slugSaveBtn) {
    slugSaveBtn.addEventListener("click", async () => {
      const slug = slugInput.value.trim().toLowerCase();
      if (!slug) return;
      const res = await apiFetch("/slug", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { showToast(data.error || "Could not set URL name", "error"); return; }
      showToast("Public URL updated ✓", "success");
      const newUrl = publicUrlInput.value.replace(/\/pub\/[^/]+\//, `/pub/${data.slug}/`);
      publicUrlInput.value = newUrl;
      document.getElementById("open-url-btn").href = newUrl;
    });
  }

  // ---- Delete project ----
  if (deleteProjectBtn) {
    deleteProjectBtn.addEventListener("click", async () => {
      if (!confirm("Delete this entire project? This cannot be undone.")) return;
      const res = await fetch(`/api/projects/${projectId}`, { method: "DELETE" });
      if (res.ok) window.location.href = "/";
      else showToast("Could not delete project", "error");
    });
  }

  // ---- Run / Stop ----
  function setRunningUI(running) {
    runStatus.innerHTML = `<span class="status-dot-sm"></span>${running ? "Running" : "Stopped"}`;
    runStatus.className = "status-pill " + (running ? "running" : "stopped");
    runBtn.disabled = running;
    stopBtn.disabled = !running;
  }

  runBtn.addEventListener("click", async () => {
    runBtn.disabled = true;
    runBtn.textContent = "Starting...";
    terminalOutput.innerHTML = "";
    logsCleared = false;
    try {
      const res = await apiFetch("/run", { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast("Run failed: " + (err.error || "unknown error"), "error");
        runBtn.disabled = false;
        return;
      }
      setRunningUI(true);
      showToast("Project started ✓", "success");
    } finally {
      runBtn.innerHTML = "&#9654; Run";
    }
  });

  stopBtn.addEventListener("click", async () => {
    stopBtn.disabled = true;
    stopBtn.textContent = "Stopping...";
    const res = await apiFetch("/stop", { method: "POST" });
    stopBtn.textContent = "&#9632; Stop";
    if (res.ok) { setRunningUI(false); showToast("Project stopped", "success"); }
    else stopBtn.disabled = false;
  });

  // ---- Logs ----
  clearLogsBtn.addEventListener("click", async () => {
    logsCleared = true;
    terminalOutput.innerHTML = "";
    lastRawLog = "";
    await apiFetch("/logs/clear", { method: "POST" }).catch(() => {});
  });

  function classifyLine(line) {
    const lower = line.toLowerCase();
    if (lower.includes("traceback") || lower.includes("error") || lower.includes("exception") || lower.includes("failed")) return "log-error";
    if (lower.includes("warn")) return "log-warn";
    if (line.startsWith("[") && (line.includes("Starting:") || line.includes("process exited") || line.includes("Installing") || line.includes("Restoring"))) return "log-system";
    return "log-info";
  }

  function escapeHtml(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderLogs(rawLog) {
    if (logsCleared) return;
    const lines = rawLog.split("\n").filter((l) => l.length > 0);
    const errorsOnly = errorsOnlyToggle.checked;
    const filtered = errorsOnly
      ? lines.filter((l) => { const c = classifyLine(l); return c === "log-error" || c === "log-warn"; })
      : lines;

    if (filtered.length === 0) {
      terminalOutput.innerHTML = '<span class="log-empty">No logs yet. Hit Run to start the project.</span>';
      return;
    }

    const atBottom = terminalOutput.scrollTop + terminalOutput.clientHeight >= terminalOutput.scrollHeight - 30;
    terminalOutput.innerHTML = filtered
      .map((line) => `<span class="log-line ${classifyLine(line)}">${escapeHtml(line)}</span>`)
      .join("\n");

    if (autoscrollToggle.checked && atBottom) {
      terminalOutput.scrollTop = terminalOutput.scrollHeight;
    }
  }

  errorsOnlyToggle.addEventListener("change", () => renderLogs(lastRawLog));

  async function pollLogs() {
    try {
      const res = await apiFetch("/logs");
      if (res.ok) {
        const data = await res.json();
        const newLog = data.log || "";
        if (newLog !== lastRawLog) {
          lastRawLog = newLog;
          renderLogs(lastRawLog);
        }
        setRunningUI(data.running);
      }
    } catch (_e) { /* ignore transient errors */ }
    setTimeout(pollLogs, 2000);
  }

  // ---- Auto-ping status ----
  async function checkPingStatus() {
    try {
      const res = await fetch("/api/ping-config");
      if (res.ok) {
        const data = await res.json();
        if (data.enabled) {
          pingBadge.textContent = `🟢 ping on (every ${Math.round(data.ping_interval / 60)}min)`;
          pingBadge.title = `Pinging: ${data.ping_url}`;
        } else {
          pingBadge.textContent = "🔴 ping off";
          pingBadge.title = "Set RENDER_EXTERNAL_URL or PING_URL env var to enable auto-ping";
        }
      }
    } catch (_e) {}
  }

  // Initial load
  loadFiles(true);
  loadEnv();
  pollLogs();
  checkPingStatus();
  renderLogs("");
})();

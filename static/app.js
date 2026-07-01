(function () {
  const layout = document.querySelector(".project-layout");
  if (!layout) return; // dashboard page, nothing to wire up here

  const projectId = layout.dataset.projectId;
  const fileListEl = document.getElementById("file-list");
  const editor = document.getElementById("code-editor");
  const currentFileLabel = document.getElementById("current-file-label");
  const unsavedDot = document.getElementById("unsaved-dot");
  const saveStatus = document.getElementById("save-status");
  const saveBtn = document.getElementById("save-btn");
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
  const entryFileInput = document.getElementById("entry-file");
  const entrySaveBtn = document.getElementById("entry-save-btn");
  const publicUrlInput = document.getElementById("public-url-input");
  const copyUrlBtn = document.getElementById("copy-url-btn");
  const slugInput = document.getElementById("slug-input");
  const slugSaveBtn = document.getElementById("slug-save-btn");
  const errorsOnlyToggle = document.getElementById("errors-only-toggle");
  const clearLogsBtn = document.getElementById("clear-logs-btn");
  const toastContainer = document.getElementById("toast-container");

  let currentFile = null;
  let dirty = false;
  let envVars = {};
  let lastRawLog = "";
  let logsCleared = false;

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
    const res = await fetch(apiUrl(path), options);
    if (res.status === 401) {
      showToast("Session expired — please log in again.", "error");
      setTimeout(() => (window.location.href = "/login"), 1200);
      throw new Error("unauthorized");
    }
    return res;
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
      del.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete ${f.path}?`)) return;
        await apiFetch(`/file?path=${encodeURIComponent(f.path)}`, { method: "DELETE" });
        if (currentFile === f.path) {
          currentFile = null;
          editor.value = "";
          currentFileLabel.textContent = "No file open";
        }
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
    if (!res.ok) {
      showToast("Could not open " + path, "error");
      return;
    }
    const data = await res.json();
    currentFile = path;
    editor.value = data.content;
    currentFileLabel.textContent = path;
    setDirty(false);
    loadFiles(false);
  }

  async function saveCurrentFile() {
    if (!currentFile) {
      flashSaveStatus("Open a file first", true);
      return;
    }
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
      const start = editor.selectionStart;
      const end = editor.selectionEnd;
      editor.value = editor.value.slice(0, start) + "    " + editor.value.slice(end);
      editor.selectionStart = editor.selectionEnd = start + 4;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      saveCurrentFile();
    }
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
      showToast("Repo imported", "success");
      currentFile = null;
      await loadFiles(true);
    } finally {
      githubImportBtn.textContent = "Import repo";
      githubImportBtn.disabled = false;
    }
  });

  function renderEnvList() {
    envList.innerHTML = "";
    Object.entries(envVars).forEach(([key, value]) => {
      const row = document.createElement("div");
      row.className = "env-item";
      const label = document.createElement("span");
      label.textContent = `${key} = ${value}`;
      const remove = document.createElement("span");
      remove.textContent = "✕";
      remove.className = "env-remove";
      remove.addEventListener("click", () => {
        delete envVars[key];
        saveEnv();
      });
      row.appendChild(label);
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
    if (res.ok) {
      showToast("Environment variables saved", "success");
    } else {
      showToast("Could not save environment variables", "error");
    }
    renderEnvList();
  }

  envAddBtn.addEventListener("click", () => {
    const key = envKeyInput.value.trim();
    const value = envValueInput.value;
    if (!key) return;
    envVars[key] = value;
    envKeyInput.value = "";
    envValueInput.value = "";
    saveEnv();
  });

  entrySaveBtn.addEventListener("click", async () => {
    const res = await apiFetch("/entry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entry_file: entryFileInput.value.trim() }),
    });
    showToast(res.ok ? "Entry file saved" : "Could not save entry file", res.ok ? "success" : "error");
  });

  if (copyUrlBtn) {
    copyUrlBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(publicUrlInput.value);
        showToast("Public URL copied", "success");
      } catch (_e) {
        publicUrlInput.select();
        showToast("Select and copy the URL manually", "error");
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
      if (!res.ok) {
        showToast(data.error || "Could not set public URL name", "error");
        return;
      }
      showToast("Public URL updated", "success");
      const newUrl = publicUrlInput.value.replace(/\/pub\/[^/]+\//, `/pub/${data.slug}/`);
      publicUrlInput.value = newUrl;
      document.getElementById("open-url-btn").href = newUrl;
    });
  }

  function setRunningUI(running) {
    runStatus.textContent = running ? "running" : "stopped";
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
    } finally {
      runBtn.textContent = "Run";
    }
  });

  stopBtn.addEventListener("click", async () => {
    stopBtn.disabled = true;
    stopBtn.textContent = "Stopping...";
    const res = await apiFetch("/stop", { method: "POST" });
    stopBtn.textContent = "Stop";
    if (res.ok) setRunningUI(false);
    else stopBtn.disabled = false;
  });

  clearLogsBtn.addEventListener("click", () => {
    logsCleared = true;
    terminalOutput.innerHTML = "";
  });

  function classifyLine(line) {
    const lower = line.toLowerCase();
    if (lower.includes("traceback") || lower.includes("error") || lower.includes("exception") || lower.includes("failed")) {
      return "log-error";
    }
    if (lower.includes("warn")) return "log-warn";
    if (line.startsWith("[") && (line.includes("Starting:") || line.includes("process exited") || line.includes("Installing"))) {
      return "log-system";
    }
    return "log-info";
  }

  function escapeHtml(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderLogs(rawLog) {
    if (logsCleared) return;
    const lines = rawLog.split("\n").filter((l) => l.length > 0);
    const filtered = errorsOnlyToggle.checked
      ? lines.filter((l) => classifyLine(l) === "log-error" || classifyLine(l) === "log-warn")
      : lines;
    const atBottom = terminalOutput.scrollTop + terminalOutput.clientHeight >= terminalOutput.scrollHeight - 20;
    terminalOutput.innerHTML = filtered
      .map((line) => `<span class="log-line ${classifyLine(line)}">${escapeHtml(line)}</span>`)
      .join("\n");
    if (atBottom) terminalOutput.scrollTop = terminalOutput.scrollHeight;
  }

  errorsOnlyToggle.addEventListener("change", () => renderLogs(lastRawLog));

  async function pollLogs() {
    try {
      const res = await apiFetch("/logs");
      if (res.ok) {
        const data = await res.json();
        lastRawLog = data.log || "";
        renderLogs(lastRawLog);
        setRunningUI(data.running);
      }
    } catch (_e) {
      // ignore transient network errors between polls
    }
    setTimeout(pollLogs, 2000);
  }

  // Initial load
  loadFiles(true);
  loadEnv();
  pollLogs();
})();

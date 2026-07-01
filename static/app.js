(function () {
  const layout = document.querySelector(".project-layout");
  if (!layout) return; // dashboard page, nothing to wire up here

  const projectId = layout.dataset.projectId;
  const fileListEl = document.getElementById("file-list");
  const editor = document.getElementById("code-editor");
  const currentFileLabel = document.getElementById("current-file-label");
  const unsavedDot = document.getElementById("unsaved-dot");
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

  let currentFile = null;
  let dirty = false;
  let envVars = {};

  function apiUrl(path) {
    return `/api/projects/${projectId}${path}`;
  }

  function setDirty(value) {
    dirty = value;
    unsavedDot.classList.toggle("hidden", !dirty);
  }

  async function loadFiles(selectFirst) {
    const res = await fetch(apiUrl("/files"));
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
        await fetch(apiUrl(`/file?path=${encodeURIComponent(f.path)}`), { method: "DELETE" });
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
    const res = await fetch(apiUrl(`/file?path=${encodeURIComponent(path)}`));
    if (!res.ok) return;
    const data = await res.json();
    currentFile = path;
    editor.value = data.content;
    currentFileLabel.textContent = path;
    setDirty(false);
    loadFiles(false);
  }

  async function saveCurrentFile() {
    if (!currentFile) return;
    await fetch(apiUrl("/file"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: currentFile, content: editor.value }),
    });
    setDirty(false);
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
    await fetch(apiUrl("/file"), {
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
    await fetch(apiUrl("/upload"), { method: "POST", body: formData });
    uploadInput.value = "";
    loadFiles(false);
  });

  githubImportBtn.addEventListener("click", async () => {
    const url = githubUrlInput.value.trim();
    if (!url) return;
    githubImportBtn.textContent = "Importing...";
    githubImportBtn.disabled = true;
    const res = await fetch(apiUrl("/github"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_url: url }),
    });
    githubImportBtn.textContent = "Import repo";
    githubImportBtn.disabled = false;
    if (!res.ok) {
      const err = await res.json();
      alert("Import failed: " + (err.error || "unknown error"));
      return;
    }
    currentFile = null;
    await loadFiles(true);
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
    const res = await fetch(apiUrl("/env"));
    const data = await res.json();
    envVars = data.env || {};
    renderEnvList();
  }

  async function saveEnv() {
    await fetch(apiUrl("/env"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ env: envVars }),
    });
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
    await fetch(apiUrl("/entry"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entry_file: entryFileInput.value.trim() }),
    });
  });

  function setRunningUI(running) {
    runStatus.textContent = running ? "running" : "stopped";
    runStatus.className = "status-pill " + (running ? "running" : "stopped");
    runBtn.disabled = running;
    stopBtn.disabled = !running;
  }

  runBtn.addEventListener("click", async () => {
    terminalOutput.textContent = "";
    const res = await fetch(apiUrl("/run"), { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      alert("Run failed: " + (err.error || "unknown error"));
      return;
    }
    setRunningUI(true);
  });

  stopBtn.addEventListener("click", async () => {
    const res = await fetch(apiUrl("/stop"), { method: "POST" });
    if (res.ok) setRunningUI(false);
  });

  async function pollLogs() {
    try {
      const res = await fetch(apiUrl("/logs"));
      if (res.ok) {
        const data = await res.json();
        const atBottom = terminalOutput.scrollTop + terminalOutput.clientHeight >= terminalOutput.scrollHeight - 20;
        terminalOutput.textContent = data.log;
        if (atBottom) terminalOutput.scrollTop = terminalOutput.scrollHeight;
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

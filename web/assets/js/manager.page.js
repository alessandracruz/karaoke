// web/assets/js/manager.page.js
let currentSelected = null;

function qs(sel, root = document) { return root.querySelector(sel); }
function qsa(sel, root = document) { return [...root.querySelectorAll(sel)]; }

function getApi() {
  // pywebview injeta window.pywebview.api quando roda dentro do app
  return window.pywebview?.api ?? null;
}

function setActiveTab(tabId) {
  qsa(".tab").forEach(t => t.classList.remove("active"));
  qsa(".content").forEach(c => c.classList.remove("active"));

  const tabSearch = qs("#tab-search");
  const tabBulk = qs("#tab-bulk");

  if (tabId === "search") tabSearch?.classList.add("active");
  else tabBulk?.classList.add("active");

  qs(`#${tabId}`)?.classList.add("active");
}

function handleEnter(e) {
  if (e.key === "Enter") performSearch();
}

async function performSearch() {
  const api = getApi();
  const query = qs("#query")?.value?.trim();
  if (!query) return;

  qs("#search-loading").style.display = "block";
  qs("#results").innerHTML = "";

  if (!api) {
    // fallback amigável quando estiver só no http.server
    qs("#results").textContent = "pywebview.api não disponível (abra via app Python para buscar).";
    qs("#search-loading").style.display = "none";
    return;
  }

  try {
    const results = await api.search(query);
    renderResults(Array.isArray(results) ? results : []);
  } catch (err) {
    console.error(err);
    const box = qs("#results");
    box.textContent = "Erro ao buscar.";
  } finally {
    qs("#search-loading").style.display = "none";
  }
}

function renderResults(results) {
  const container = qs("#results");
  container.innerHTML = "";

  if (!results.length) {
    const empty = document.createElement("div");
    empty.style.padding = "10px";
    empty.textContent = "No results found.";
    container.appendChild(empty);
    return;
  }

  for (const song of results) {
    const item = document.createElement("div");
    item.className = "result-item";
    item.addEventListener("click", () => selectSong(song));

    const info = document.createElement("div");
    info.className = "result-info";

    const title = document.createElement("div");
    title.textContent = song?.title ?? "";

    const artist = document.createElement("div");
    artist.textContent = song?.artist ?? "";

    info.appendChild(title);
    info.appendChild(artist);
    item.appendChild(info);

    container.appendChild(item);
  }
}

function selectSong(song) {
  currentSelected = song;

  qs("#selected-title").innerText = song?.title ?? "Select a song";
  qs("#selected-artist").innerText = song?.artist ?? "To preview and download";
  qs("#btn-download").disabled = false;
  qs("#download-status").innerText = "";

  const videoId = song?.videoId ?? "";
  qs("#preview-frame").src = `https://www.youtube.com/embed/${videoId}?autoplay=0&origin=https://youtube.com`;
}

async function downloadSelected() {
  const api = getApi();
  if (!api) {
    qs("#download-status").innerText = "pywebview.api não disponível (abra via app Python).";
    return;
  }
  if (!currentSelected) return;

  const btn = qs("#btn-download");
  const status = qs("#download-status");

  btn.disabled = true;
  btn.innerText = "Downloading...";
  status.innerText = "Starting download...";

  try {
    const result = await api.download(
      currentSelected.videoId,
      currentSelected.title,
      currentSelected.artist
    );
    status.innerText = String(result);
  } catch (error) {
    status.innerText = "Error: " + error;
  } finally {
    btn.disabled = false;
    btn.innerText = "Download Selected";
  }
}

async function startBulkDownload() {
  const api = getApi();
  const text = qs("#bulk-input")?.value ?? "";
  if (!text.trim()) return;

  const log = qs("#bulk-log");
  log.innerText += "Starting bulk process...\n";

  if (!api) {
    log.innerText += "pywebview.api não disponível (abra via app Python).\n";
    return;
  }

  try {
    await api.bulk_download(text);
  } catch (e) {
    log.innerText += "Error triggering bulk: " + e + "\n";
  }
}

// Expor para o Python chamar
function logBulk(message) {
  const log = qs("#bulk-log");
  if (log) {
    log.innerText += message + "\n";
    log.scrollTop = log.scrollHeight;
  }

  const status = qs("#download-status");
  if (status && typeof message === "string" && message.length < 100) {
    status.innerText = message;
  }
}

function wireUI() {
  qs("#tab-search")?.addEventListener("click", () => setActiveTab("search"));
  qs("#tab-bulk")?.addEventListener("click", () => setActiveTab("bulk"));

  qs("#query")?.addEventListener("keydown", handleEnter);
  qs("#btn-search")?.addEventListener("click", performSearch);

  qs("#btn-download")?.addEventListener("click", downloadSelected);
  qs("#btn-bulk-download")?.addEventListener("click", startBulkDownload);
}

document.addEventListener("DOMContentLoaded", () => {
  wireUI();
  // garante estado inicial igual ao HTML
  setActiveTab("search");
});

window.logBulk = logBulk;

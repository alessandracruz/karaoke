// singer.js (v1) - performance-first, safe DOM rendering (no innerHTML)

(function () {
  "use strict";

  function byId(id) {
    return document.getElementById(id);
  }

  const els = {
    status: byId("singer-status"),
    playing: byId("singer-playing"),
    title: byId("song-title"),
    artist: byId("song-artist"),
    current: byId("lyrics-current"),
    next: byId("lyrics-next"),
  };

  function setHidden(el, hidden) {
    if (!el) return;
    if (hidden) el.setAttribute("hidden", "");
    else el.removeAttribute("hidden");
  }

  function clearNode(node) {
    if (!node) return;
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function renderStandby() {
    setHidden(els.status, false);
    setHidden(els.playing, true);
  }



  function renderPlaying(data) {
    // data: { title, artist, currentLine, nextLines[] }
    if (!data) return;

    if (els.title) els.title.textContent = data.title || "";
    if (els.artist) els.artist.textContent = data.artist || "";
    if (els.current) els.current.textContent = data.currentLine || "";

    clearNode(els.next);
    if (els.next && Array.isArray(data.nextLines)) {
      const maxItems = 3; // keep DOM small (v1)
      for (let i = 0; i < data.nextLines.length && i < maxItems; i += 1) {
        const li = document.createElement("li");
        li.textContent = String(data.nextLines[i] ?? "");
        els.next.appendChild(li);
      }
    }

    setHidden(els.status, true);
    setHidden(els.playing, false);
  }

  function init() {
    // Default state (v1)
    renderStandby();

    const DEV_PREVIEW = false;
    /*
    if (DEV_PREVIEW) {
        renderPlaying({
        title: "Evidências",
        artist: "Chitãozinho & Xororó",
        currentLine: "E nessa loucura de dizer que não te quero...",
        nextLines: [
            "Vou negando as aparências",
            "Disfarçando as evidências",
            "Mas pra que viver fingindo?",
        ],
        });
    }
    */

    // Expose minimal API for future polling integration (v1)
    window.KaraokeSinger = {
      renderStandby,
      renderPlaying,
    };
  }

  document.addEventListener("DOMContentLoaded", init);
})();

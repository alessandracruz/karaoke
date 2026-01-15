import { qs, el, mockCatalog } from "./app.js";

const state = {
  catalog: mockCatalog(),
  queue: [],
};

function badge(text, kind){
  return el("span", { class: `badge ${kind||""}` }, [text]);
}

function renderCatalog(){
  const wrap = qs("[data-catalog]");
  wrap.innerHTML = "";

  state.catalog.forEach(song => {
    const statusBadges = [
      song.lyricOk ? badge("Letra OK", "ok") : badge("Sem letra", "err"),
      song.instOk ? badge("Instrumental OK", "ok") : badge("Sem instrumental", "warn"),
    ];

    if(song.status === "processando") statusBadges.push(badge("Processando...", "warn"));

    const card = el("div", { class:"card" }, [
      el("div", { class:"title" }, [song.title]),
      el("div", { class:"sub" }, [`${song.artist} • ${song.duration}`]),
      el("div", { class:"row" }, statusBadges),
      el("div", { class:"actions" }, [
        el("button", {
          class:"btn btn-accent",
          onClick: () => addToQueue(song.id)
        }, ["Adicionar à fila"])
      ])
    ]);

    wrap.appendChild(card);
  });
}

function renderQueue(){
  const wrap = qs("[data-queue]");
  wrap.innerHTML = "";

  if(state.queue.length === 0){
    wrap.appendChild(el("div", { class:"queue-empty" }, ["Nenhuma música na fila"]));
    return;
  }

  state.queue.forEach((song, idx) => {
    wrap.appendChild(el("div", { class:"queue-item" }, [
      el("div", {}, [
        el("div", { style:"font-weight:700" }, [song.title]),
        el("div", { class:"meta" }, [`${song.artist} • ${song.duration}`]),
      ]),
      el("div", { style:"display:flex; gap:8px; align-items:center" }, [
        el("button", { class:"btn", onClick: () => move(idx, -1) }, ["↑"]),
        el("button", { class:"btn", onClick: () => move(idx, +1) }, ["↓"]),
        el("button", { class:"btn", onClick: () => remove(idx) }, ["Remover"]),
      ])
    ]));
  });
}

function addToQueue(id){
  const song = state.catalog.find(s => s.id === id);
  if(!song) return;
  state.queue.push(song);
  renderQueue();
}

function move(i, delta){
  const j = i + delta;
  if(j < 0 || j >= state.queue.length) return;
  [state.queue[i], state.queue[j]] = [state.queue[j], state.queue[i]];
  renderQueue();
}

function remove(i){
  state.queue.splice(i, 1);
  renderQueue();
}

function wireImport(){
  const input = qs("[data-import-input]");
  const btn = qs("[data-import-btn]");
  btn.addEventListener("click", () => {
    const v = input.value.trim();
    if(!v) return;
    // aqui depois vira chamada de backend (enqueue import job)
    alert("Stub: enviar para backend importar -> " + v);
    input.value = "";
  });
}

function main(){
  renderCatalog();
  renderQueue();
  wireImport();
}

document.addEventListener("DOMContentLoaded", main);

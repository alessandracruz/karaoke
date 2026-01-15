export function qs(sel, root=document){ return root.querySelector(sel); }
export function qsa(sel, root=document){ return [...root.querySelectorAll(sel)]; }

export function el(tag, attrs = {}, children = []){
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k,v]) => {
    if(k === "class") node.className = v;
    else if(k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  });
  children.forEach(c => node.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
  return node;
}

// mock do catálogo por enquanto (depois vira fetch do backend)
export function mockCatalog(){
  return [
    { id:"1", title:"Clássico", artist:"Grupo X", duration:"4:01", lyricOk:true, instOk:true },
    { id:"2", title:"Estilo", artist:"-", duration:"2:51", lyricOk:true, instOk:false, status:"processando" },
    { id:"3", title:"Hit", artist:"Cantor F", duration:"3:12", lyricOk:true, instOk:true },
    { id:"4", title:"Music B", artist:"Banda Q", duration:"3:32", lyricOk:true, instOk:true },
    { id:"5", title:"Música", artist:"Admin C", duration:"3:14", lyricOk:true, instOk:true },
    { id:"6", title:"Sucesso", artist:"Banda A", duration:"2:45", lyricOk:true, instOk:true },
  ];
}

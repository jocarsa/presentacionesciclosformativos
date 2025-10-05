#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mapamental.py — mindmap colapsado, radial estable, “entrar” y “+” por nodo, enlaces a presentaciones.

Estructura: Ciclos (carpetas) → Asignaturas (.md) → Unidades (cabeceras) → Subunidades (bullets o ##/###).
- Clic en la ETIQUETA de un nodo no hoja  => ENTRAR (ese nodo pasa a ser el root visible).
- Clic en el botón +/− de un nodo         => expandir/plegar SIN re-enfocar (no cambia el root).
- Clic en una SUBUNIDAD con enlace        => abre la presentación HTML (no se inserta contenido).
"""

import os
import re
import json
import unicodedata
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# ========= Paths (ajusta si es necesario) =========
ROOT_DIR = Path(".").resolve()   # carpeta raíz que contiene las carpetas de “ciclo”
def _autodetect_presentations(start: Path) -> Path:
    for c in [start/"presentations", start.parent/"presentations",
              start/"presentaciones", start.parent/"presentaciones"]:
        if c.exists() and c.is_dir():
            return c.resolve()
    return (start/"presentations").resolve()

PRESENTATIONS_DIR = _autodetect_presentations(ROOT_DIR)
OUT_HTML = (ROOT_DIR / "mindmap.html").resolve()
# ================================================


# ---------- utils ----------
def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9\-_.]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "item"

def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[ERROR leyendo {path}: {e}]"

# ---------- parsing ----------
# bullets for subunidades
BULLET_L2 = r"^[\-\u2212\u2013\u2014\*\u2022]\s+"  # -, −, –, —, *, •
BULLET_L3 = r"^[\u00B7\*\u2022]\s+"                # ·, *, •

HEADER_H1 = re.compile(r"^#\s+(.+)$")
HEADER_H2 = re.compile(r"^##\s+(.+)$")
HEADER_H3 = re.compile(r"^###\s+(.+)$")
SETEXT_H1 = re.compile(r"^=+\s*$")
SETEXT_H2 = re.compile(r"^-{3,}\s*$")

def parse_units_and_subunits(md_text: str) -> List[Dict]:
    """
    Units = Markdown H1 (# …) o Setext (Título + === / ---).
    Subunits = bullets bajo la unidad, o H2/H3 bajo esa unidad.
    """
    lines = md_text.splitlines()
    units: List[Dict] = []
    current_unit = None
    current_subunit = None

    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        stripped = line.strip()

        # H1 como unidad
        m_h1 = HEADER_H1.match(stripped)
        if m_h1:
            current_unit = {"unit_title": m_h1.group(1).strip(), "subunits": []}
            units.append(current_unit)
            current_subunit = None
            i += 1
            continue

        # Setext H1/H2
        if stripped and i+1 < len(lines):
            next_line = lines[i+1].strip()
            if SETEXT_H1.match(next_line) or SETEXT_H2.match(next_line):
                current_unit = {"unit_title": stripped, "subunits": []}
                units.append(current_unit)
                current_subunit = None
                i += 2
                continue

        # H2/H3 como subunidad (si hay unidad)
        m_h2 = HEADER_H2.match(stripped)
        if m_h2 and current_unit:
            current_subunit = {"subunit_title": m_h2.group(1).strip(), "subtopics": []}
            current_unit["subunits"].append(current_subunit)
            i += 1
            continue

        m_h3 = HEADER_H3.match(stripped)
        if m_h3 and current_unit:
            current_subunit = {"subunit_title": m_h3.group(1).strip(), "subtopics": []}
            current_unit["subunits"].append(current_subunit)
            i += 1
            continue

        # Bullets como subunidad (si hay unidad)
        if current_unit and re.match(BULLET_L2, stripped):
            title = re.sub(BULLET_L2, "", stripped).strip()
            current_subunit = {"subunit_title": title, "subtopics": []}
            current_unit["subunits"].append(current_subunit)
            i += 1
            continue

        # Bullets anidados como subtopics (no se dibujan)
        if current_subunit and re.match(BULLET_L3, stripped):
            topic = re.sub(BULLET_L3, "", stripped).strip()
            current_subunit.setdefault("subtopics", []).append(topic)
            i += 1
            continue

        i += 1

    # Orden estable por título
    for u in units:
        u["subunits"].sort(key=lambda s: s.get("subunit_title","").lower())
    units.sort(key=lambda u: u.get("unit_title","").lower())
    return units

# ---------- link finder ----------
def find_presentation_href(presentations_root: Path,
                           doc_name_no_ext: str,
                           unit_title: str,
                           subunit_title: str) -> Optional[str]:
    """
    Busca presentations/<slug(doc_name)>/<unit>__<sub>* .html
    Devuelve ruta RELATIVA al directorio de OUT_HTML (raíz del repo).
    """
    # La herramienta de presentaciones usa: slugify(doc_name.replace(".md",""))
    doc_slug = slugify(doc_name_no_ext)  # ojo: usamos el nombre COMPLETO sin .md (con números/espacios)
    unit_slug = slugify(unit_title)
    sub_slug  = slugify(subunit_title)

    doc_dir = presentations_root / doc_slug
    if not doc_dir.exists():
        return None

    patterns = [
        f"*{unit_slug}__*{sub_slug}*.html",
        f"*__*{sub_slug}*.html",
    ]
    candidates: List[Path] = []
    for pat in patterns:
        candidates.extend(doc_dir.glob(pat))
    if not candidates:
        return None
    best = max(candidates, key=lambda p: p.stat().st_mtime)

    # Relativo al HTML de salida (que está en ROOT_DIR)
    return os.path.relpath(best, start=OUT_HTML.parent)

# ---------- build tree ----------
def build_tree(root_dir: Path, presentations_root: Path) -> Dict:
    tree = {"title": "ROOT", "type": "root", "children": []}
    for cycle_dir in sorted([p for p in root_dir.iterdir()
                             if p.is_dir() and p.name.lower() not in {"presentations","presentaciones"}],
                            key=lambda p: p.name.lower()):
        cycle_node = {"title": cycle_dir.name, "type": "cycle", "children": []}
        md_files = sorted(cycle_dir.glob("*.md"), key=lambda p: p.name.lower())
        for md_path in md_files:
            units = parse_units_and_subunits(read_text(md_path))
            doc_node = {
                "title": md_path.name,
                "type": "subject",
                "doc_slug": slugify(md_path.name.replace(".md","")),  # igual que el generador
                "children": [],
            }
            for u_idx, unit in enumerate(units, start=1):
                unit_title = unit.get("unit_title") or f"Unidad {u_idx}"
                unit_node = {"title": unit_title, "type": "unit", "children": []}
                for s_idx, sub in enumerate(unit.get("subunits", []), start=1):
                    sub_title = sub.get("subunit_title") or f"Subunidad {u_idx}.{s_idx}"
                    href = find_presentation_href(presentations_root, md_path.name.replace(".md",""),
                                                  unit_title, sub_title)
                    unit_node["children"].append({"title": sub_title, "type": "subunit", "url": href})
                if unit_node["children"]:
                    doc_node["children"].append(unit_node)
            if doc_node["children"]:
                cycle_node["children"].append(doc_node)
        tree["children"].append(cycle_node)
    return tree

# ---------- HTML (light theme, radial estable, enter/+ UI) ----------
HTML = """<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><title>Mindmap de contenidos</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{
  /* Light theme */
  --bg:#f6f7fb;          /* page background */
  --fg:#111827;          /* text color (near-black) */
  --muted:#475569;       /* secondary text */
  --accent:#2563eb;      /* blue accents */
  --ok:#16a34a;          /* green outline for linked subunits */
  --warn:#d97706;        /* amber outline for missing links */
  --card:#ffffff;        /* node background */
}
*{box-sizing:border-box}
body{
  margin:0;background:var(--bg);color:var(--fg);
  font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,Noto Sans,Arial,sans-serif;
  overflow:hidden;
}
.header{
  display:flex;align-items:center;gap:1rem;
  padding:.75rem 1rem;border-bottom:1px solid #e2e8f0;
  background:rgba(255,255,255,.9);backdrop-filter:saturate(120%) blur(6px);
}
.header h1{font-size:1.1rem;margin:0;white-space:nowrap}
.header .meta{color:var(--muted);font-size:.9rem}
#crumbs{display:flex;gap:.5rem;align-items:center}
#crumbs a{color:var(--accent);text-decoration:none;font-weight:600}
#stage{position:fixed;inset:3rem 0 0 0}
svg{width:100%;height:100%}
.node rect{
  fill:var(--card);
  stroke:#cbd5e1; stroke-width:1; rx:10; ry:10;
  filter: drop-shadow(0 2px 2px rgba(0,0,0,.05));
}
.label{font-size:.9rem; fill:var(--fg)}
.badge{font-size:.8rem; fill:#0f172a}
.badge-bg{fill:#e2e8f0; rx:8; ry:8}
.node.subunit.haslink rect{stroke:var(--ok)}
.node.subunit.missing rect{stroke:var(--warn)}
.link{fill:none;stroke:#94a3b8;stroke-width:1.5}
.controls{margin-left:auto;display:flex;gap:.4rem}
.controls button{
  appearance:none;background:#ffffff;color:var(--fg);
  border:1px solid #cbd5e1;border-radius:8px;padding:.3rem .6rem;cursor:pointer
}
.controls button:hover{border-color:#94a3b8;background:#f8fafc}
.legend{display:flex;align-items:center;gap:.75rem;margin-left:1rem}
.legend .box{width:14px;height:14px;border-radius:4px}
.legend .ok{border:2px solid var(--ok)} .legend .warn{border:2px solid var(--warn)}
.tip{color:var(--muted);font-size:.9rem;margin-left:1rem}
</style></head>
<body>
<div class="header">
  <h1>Mindmap de contenidos</h1>
  <div id="crumbs" class="meta"></div>
  <div class="meta" id="stats"></div>
  <div class="legend"><span class="box ok"></span><span>con presentación</span><span class="box warn"></span><span>sin presentación</span></div>
  <div class="tip">clic etiqueta = entrar · clic +/− = expandir/plegar · clic subunidad con enlace = abrir</div>
  <div class="controls"><button id="fit">Ajustar</button><button id="zoomOut">−</button><button id="zoomReset">100%</button><button id="zoomIn">+</button></div>
</div>
<div id="stage"><svg id="svg" viewBox="0 0 1200 800" preserveAspectRatio="xMidYMid meet"></svg></div>
<script>
const ROOT = __DATA__;

/* ---------- indexado & estado ---------- */
let idCounter=0, index=new Map(), parentMap=new Map();
function indexTree(n,p=null){
  n._id=idCounter++; index.set(n._id,n);
  if(p){ parentMap.set(n._id,p._id); }
  if(Array.isArray(n.children)) n.children.forEach(c=>indexTree(c,n));
}
indexTree(ROOT);

function pathToRoot(id){
  const arr=[]; let cur=id;
  while(cur!=null){
    arr.push(cur);
    cur = parentMap.has(cur) ? parentMap.get(cur) : null;
  }
  return arr.reverse();
}

// Conjunto de nodos expandidos (por defecto, solo el root y los ciclos directos opcionalmente)
const expanded = new Set();
expanded.add(ROOT._id); // root visible
// currentRoot controla el SUB-árbol que se distribuye radialmente (estabilidad geométrica)
let currentRoot = ROOT._id;

/* ---------- helpers visibilidad ---------- */
function childrenOf(id){
  const n = index.get(id);
  const kids = (n && n.children) ? [...n.children] : [];
  // orden estable por título
  kids.sort((a,b)=> (a.title||'').localeCompare(b.title||''));
  return kids;
}

function isExpanded(id){ return expanded.has(id); }

function visibleChildren(id){
  return isExpanded(id) ? childrenOf(id) : [];
}

/* ---------- conteo hojas visibles ---------- */
function countLeaves(id){
  const kids = visibleChildren(id);
  if(!kids.length) return 1;
  return kids.map(k=>countLeaves(k._id)).reduce((a,b)=>a+b,0);
}

/* ---------- layout radial del SUB-árbol actual ---------- */
function layoutFromRoot(rootId, radiusStep=140, angleSpan=2*Math.PI){
  const nodes=[], links=[];
  function L(id, depth, a0, a1, parent=null){
    const n = index.get(id); if(!n) return;
    const ang=(a0+a1)/2, r=depth*radiusStep, x=600+r*Math.cos(ang), y=400+r*Math.sin(ang);
    nodes.push({
      id, title:n.title||'(sin título)', type:n.type||'node', url:n.url||null,
      depth, x, y, hasChildren: (n.children&&n.children.length)>0, expanded:isExpanded(id)
    });
    if(parent!=null) links.push({s:parent, t:id});
    const kids = visibleChildren(id);
    if(kids.length){
      let acc=a0; const total=countLeaves(id);
      for(const k of kids){
        const w=countLeaves(k._id)/total*angleSpan;
        L(k._id, depth+1, acc, acc+w, id);
        acc+=w;
      }
    }
  }
  L(rootId, 0, -Math.PI/2, Math.PI*1.5, null);
  return {nodes, links};
}

/* ---------- render ---------- */
const svg=document.getElementById('svg'); let view={x:0,y:0,s:1};

function setView(){const w=1200/view.s,h=800/view.s;svg.setAttribute('viewBox',`${view.x-(w-1200)/2} ${view.y-(h-800)/2} ${w} ${h}`);}
function zoomTo(z){view.s=Math.max(.4,Math.min(2.5,z));setView();}
function pan(dx,dy){view.x+=dx;view.y+=dy;setView();}

function updateBreadcrumb(){
  const crumbs=document.getElementById('crumbs'); crumbs.innerHTML='';
  const path=pathToRoot(currentRoot).map(id=>index.get(id));
  const home=document.createElement('a'); home.textContent='Home'; home.href='#';
  home.onclick=(e)=>{e.preventDefault(); currentRoot=ROOT._id; render();};
  crumbs.appendChild(home);
  path.slice(1).forEach((n,i)=>{
    const sep=document.createTextNode(' / ');
    crumbs.appendChild(sep);
    const a=document.createElement('a'); a.textContent=n.title; a.href='#';
    a.onclick=(e)=>{e.preventDefault(); currentRoot=n._id; expanded.add(n._id); render();};
    crumbs.appendChild(a);
  });
}

function render(){
  svg.innerHTML='';
  updateBreadcrumb();
  const {nodes,links}=layoutFromRoot(currentRoot);

  // edges
  for(const l of links){
    const a=nodes.find(n=>n.id===l.s), b=nodes.find(n=>n.id===l.t);
    const p=document.createElementNS('http://www.w3.org/2000/svg','path');
    p.setAttribute('d',`M ${a.x} ${a.y} Q ${(a.x+b.x)/2} ${(a.y+b.y)/2} ${b.x} ${b.y}`);
    p.setAttribute('class','link');
    svg.appendChild(p);
  }

  // nodes
  for(const n of nodes){
    const g=document.createElementNS('http://www.w3.org/2000/svg','g');
    g.setAttribute('class',`node ${n.type}${n.type==='subunit'?(n.url?' haslink':' missing'):''}`);
    g.setAttribute('transform',`translate(${n.x},${n.y})`);

    // base rect
    const w=Math.min(42, n.title.length)*7+24, h=30;
    const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
    rect.setAttribute('x',-w/2); rect.setAttribute('y',-h/2);
    rect.setAttribute('width',w); rect.setAttribute('height',h);
    g.appendChild(rect);

    // label (click = ENTER si no es subunit; si es subunit con url => open)
    const t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('text-anchor','middle'); t.setAttribute('dominant-baseline','central'); t.setAttribute('class','label');
    t.textContent=n.title;
    g.appendChild(t);

    // +/− badge (solo nodos con hijos)
    if(n.type!=='subunit' && n.hasChildren){
      const pad=4, bx=w/2+8, by=-h/2+14;
      const badgeBg=document.createElementNS('http://www.w3.org/2000/svg','rect');
      badgeBg.setAttribute('x', bx-10); badgeBg.setAttribute('y', by-9);
      badgeBg.setAttribute('width', 20); badgeBg.setAttribute('height', 18);
      badgeBg.setAttribute('class','badge-bg');
      const badge=document.createElementNS('http://www.w3.org/2000/svg','text');
      badge.setAttribute('x', bx); badge.setAttribute('y', by);
      badge.setAttribute('text-anchor','middle'); badge.setAttribute('dominant-baseline','central');
      badge.setAttribute('class','badge');
      badge.textContent = n.expanded ? '−' : '+';
      // Toggle (NO cambia el root)
      const toggle = (e)=>{ e.stopPropagation(); if(n.expanded) expanded.delete(n.id); else expanded.add(n.id); render(); };
      badgeBg.addEventListener('click', toggle);
      badge.addEventListener('click', toggle);
      g.appendChild(badgeBg);
      g.appendChild(badge);
    }

    // click en etiqueta
    g.addEventListener('click', ()=>{
      if(n.type==='subunit'){
        if(n.url){ window.location.href = n.url; }
      }else if(n.hasChildren){
        // ENTER: ese nodo pasa a ser el root actual
        currentRoot = n.id;
        expanded.add(n.id);  // asegúrate de que muestre sus hijos
        render();
      }
    });

    svg.appendChild(g);
  }

  const stats=document.getElementById('stats');
  const subs=nodes.filter(n=>n.type==='subunit').length;
  const withLink=nodes.filter(n=>n.type==='subunit'&&n.url).length;
  stats.textContent=`${nodes.length} nodos visibles · ${subs} subunidades visibles (${withLink} con presentación)`;
}

/* ---------- pan/zoom ---------- */
let panActive=false,last={x:0,y:0};
svg.addEventListener('mousedown',e=>{panActive=true;last={x:e.clientX,y:e.clientY};});
window.addEventListener('mouseup',()=>{panActive=false;});
window.addEventListener('mousemove',e=>{if(!panActive)return;pan((last.x-e.clientX)/1.2,(last.y-e.clientY)/1.2);last={x:e.clientX,y:e.clientY};});
svg.addEventListener('wheel',e=>{e.preventDefault();zoomTo(view.s+(e.deltaY>0?-0.1:0.1));},{passive:false});
document.getElementById('zoomIn').onclick=()=>zoomTo(view.s+0.1);
document.getElementById('zoomOut').onclick=()=>zoomTo(view.s-0.1);
document.getElementById('zoomReset').onclick=()=>zoomTo(1.0);
document.getElementById('fit').onclick=()=>{view.x=0;view.y=0;zoomTo(1.0);};

render(); setView();
</script></body></html>
"""

# ---------- write & main ----------
def write_html(out_path: Path, tree: Dict):
    out_path.write_text(HTML.replace("__DATA__", json.dumps(tree, ensure_ascii=False)), encoding="utf-8")
    print(f"[OK] Mindmap generado (radial estable, enter/+): {out_path}")

def main():
    print(f"[INFO] ROOT_DIR: {ROOT_DIR}")
    print(f"[INFO] PRESENTATIONS_DIR: {PRESENTATIONS_DIR} "
          f"{'(OK)' if PRESENTATIONS_DIR.exists() else '(no existe — los enlaces no se resolverán)'}")
    print(f"[INFO] OUT_HTML: {OUT_HTML}")
    if not ROOT_DIR.exists():
        raise SystemExit(f"No existe ROOT_DIR: {ROOT_DIR}")
    tree = build_tree(ROOT_DIR, PRESENTATIONS_DIR)
    write_html(OUT_HTML, tree)

if __name__ == "__main__":
    main()


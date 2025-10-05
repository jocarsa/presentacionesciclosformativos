#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
presentaciones.py
— Genera presentaciones HTML por subunidad (nivel 2), 15–20 slides
— Streaming desde Ollama
— Limpieza de fences
— Zoom reflow (cambia font-size raíz) + Fullscreen (FS)
— Progreso fijo independiente del zoom
— Índices global y por documento
— Assets CSS/JS incrustados (se reescriben), HTMLs existentes NO se sobrescriben

NUEVO:
— Zoom reflow (textos envuelven líneas correctamente).
— Progreso visible en fullscreen + zoom.
— Evita overflow lateral (sin 100vw/100dvh).
— Todo via CSS/JS: no hace falta regenerar HTMLs.
"""

import os
import re
import json
import time
import textwrap
import argparse
import subprocess
import unicodedata
from pathlib import Path
from typing import List, Tuple, Optional, Dict

import requests

# ========================= CONFIG =========================
DEFAULT_PREFERRED = [
    "llama3.1:8b-instruct",
    "gemma2:9b-instruct",
    "qwen2.5:7b-instruct",
    "qwen2.5-coder:7b",
    "gpt-oss:20b",
]
MIN_SLIDES = 15
MAX_SLIDES_HINT = 20

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0.2"))
TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))

MAX_FILES = None
MAX_BYTES_PER_FILE = None
EXCLUDE_PATTERNS = [r"\.doc\.md$", r"^README\.md$"]

FORCE_ASSET_OVERWRITE = True  # reescribe present.css y present.js
# ==========================================================

# ========================= BRAND =========================
BRAND_NAME = ""
BRAND_PRIMARY = "#003B8E"
BRAND_ACCENT  = "#00A0E6"
BRAND_TEXT    = "#0A0A0A"
BRAND_MUTED   = "#4B5563"
BRAND_BG      = "#FFFFFF"
BRAND_FONT_STACK = "Calibri, 'Segoe UI', Roboto, Ubuntu, Cantarell, Arial, sans-serif"
BRAND_LOGO_FILENAME = "logo_ceacfp.svg"
# =========================================================

# -------------------- utilidades modelos --------------------
def list_models_http(host: str = OLLAMA_HOST) -> List[str]:
    url = f"{host.rstrip('/')}/api/tags"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    return sorted({m.get("name") for m in data.get("models", []) if m.get("name")})

def list_models_cli() -> List[str]:
    try:
        out = subprocess.check_output(["ollama", "list"], text=True, timeout=5)
    except Exception:
        return []
    models = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("name"):
            continue
        name = line.split()[0]
        models.append(name)
    return sorted(set(models))

def auto_pick_model(available: List[str]) -> Optional[str]:
    if not available:
        return None
    for pref in DEFAULT_PREFERRED:
        if pref in available: return pref
    def best_prefix_match(pref: str) -> Optional[str]:
        cand = [m for m in available if m.startswith(pref)]
        if not cand: return None
        cand.sort(key=lambda n: (0 if "instruct" in n else 1, len(n)))
        return cand[0]
    for pref in DEFAULT_PREFERRED:
        pick = best_prefix_match(pref)
        if pick: return pick
    return available[0]

# -------------------- utilidades archivos --------------------
def matches_any_pattern(name: str, patterns: List[str]) -> bool:
    return any(re.search(p, name, flags=re.IGNORECASE) for p in patterns)

def list_pure_md_files(base: Path) -> List[Path]:
    files = []
    for p in sorted(base.glob("*.md")):
        if matches_any_pattern(p.name, EXCLUDE_PATTERNS):
            continue
        files.append(p)
    if MAX_FILES:
        files = files[:MAX_FILES]
    return files

def safe_read_text(path: Path, max_bytes: Optional[int] = None) -> str:
    try:
        data = path.read_bytes()
        if max_bytes is not None and len(data) > max_bytes:
            data = data[:max_bytes]
        return data.decode("utf-8", errors="replace")
    except Exception as e:
        return f"[ERROR leyendo {path.name}: {e}]"

def build_project_context(md_files: List[Path]) -> str:
    parts = ["Contexto del proyecto (estructura y extractos):"]
    for p in md_files:
        snippet = safe_read_text(p, MAX_BYTES_PER_FILE)
        snippet = re.sub(r"\n{3,}", "\n\n", snippet).strip()
        parts.append(f"\n=== Archivo: {p.name} ===\n{snippet}\n")
    return "\n".join(parts)

def slugify(s: str) -> str:
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9\-_.]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "presentacion"

# -------------------- parsing de líneas y estructura --------------------
BULLET_L2 = r"^[\-\u2212\u2013\u2014\*\u2022]\s+"
BULLET_L3 = r"^[\u00B7\*\u2022]\s+"
UNIT_NUM_RE = re.compile(r"^\s*(\d{1,3})\.\s+(.+?)(?::\s*)?$")
SUBUNIT_NUM_RE = re.compile(r"^\s*(\d{1,3})\.(\d{1,3})\.\s+(.+?)\s*$")

def _strip_trailing_punct(s: str) -> str:
    return re.sub(r"[\.:]\s*$", "", s).strip()

def detect_level(raw_line: str) -> Tuple[int, str]:
    line = raw_line.rstrip("\n").strip()
    if not line:
        return 0, ""
    m_sub = SUBUNIT_NUM_RE.match(line)
    if m_sub:
        text = _strip_trailing_punct(m_sub.group(3))
        return 2, text
    m_unit = UNIT_NUM_RE.match(line)
    if m_unit:
        text = _strip_trailing_punct(m_unit.group(2))
        return 1, text
    if line.startswith("### "): return 3, line[4:].strip()
    if line.startswith("## "):  return 2, line[3:].strip()
    if line.startswith("# "):   return 1, line[2:].strip()
    if re.match(BULLET_L3, line): return 3, re.sub(BULLET_L3, "", line).strip()
    if re.match(BULLET_L2, line): return 2, re.sub(BULLET_L2, "", line).strip()
    if line.startswith("·"):     return 3, line.lstrip("·").strip()
    return 1, line

def parse_units_and_subunits(lines: List[str]) -> List[Dict]:
    units = []
    current_unit = None
    current_subunit = None
    for raw in lines:
        level, text = detect_level(raw)
        if level == 0:
            continue
        if level == 1:
            current_unit = {"unit_title": text, "subunits": []}
            units.append(current_unit)
            current_subunit = None
        elif level == 2:
            if current_unit is None:
                current_unit = {"unit_title": "Unidad", "subunits": []}
                units.append(current_unit)
            current_subunit = {"subunit_title": text, "subtopics": []}
            current_unit["subunits"].append(current_subunit)
        elif level == 3:
            if current_subunit is None:
                if current_unit is None:
                    current_unit = {"unit_title": "Unidad", "subunits": []}
                    units.append(current_unit)
                current_subunit = {"subunit_title": "Subunidad", "subtopics": []}
                current_unit["subunits"].append(current_subunit)
            current_subunit["subtopics"].append(text)
    return units

# -------------------- prompts --------------------
def make_subunit_prompt(doc_name: str, unit_title: str, subunit_title: str, subtopics: List[str]) -> str:
    bullet_block = "\n".join([f"- {t}" for t in subtopics]) if subtopics else "- (sin subtemas explícitos)"
    return textwrap.dedent(f"""\
    Eres un experto en formación profesional y presentaciones docentes en español.
    Genera el CONTENIDO de una presentación en HTML para la subunidad indicada.
    Devuelve EXCLUSIVAMENTE elementos <section class="slide">...</section> (sin <html>, <head> ni <body>).

    Documento: {doc_name}
    Unidad (nivel 1): {unit_title}
    Subunidad (nivel 2): {subunit_title}
    Subtemas (nivel 3):
    {bullet_block}

    REQUISITOS DE DISEÑO:
    - Crea entre {MIN_SLIDES} y {MAX_SLIDES_HINT} slides.
    - Cada slide: 80–180 palabras aprox., combinando 1–2 párrafos y/o listas (5–9 ítems).
    - Varía el tipo: concepto, ejemplo, caso, proceso, buenas prácticas, errores comunes, comparativa, mini-quiz, checklist, actividad, resumen, normativa (general).
    - PRIMERA slide = portada (<h1> título + objetivo).
    - NO estilos inline, NO <script>, solo HTML semántico dentro de <section class="slide">.
    """)

# -------------------- cliente Ollama + sanitizado --------------------
def write_stream(fh, text: str):
    fh.write(text)
    fh.flush()
    os.fsync(fh.fileno())

FENCE_OPEN_RE = re.compile(r"^\s*```(?:\s*\w+)?\s*$", re.IGNORECASE)
FENCE_ANY_RE  = re.compile(r"\s*```+\s*")
LANG_LINE_RE  = re.compile(r"^\s*(html|markdown|md|bash|sh|xml|json|javascript|js|ts|typescript|python|py|java|c\+\+|cpp|c|php|yaml|toml|ini)\s*$", re.IGNORECASE)

def sanitize_stream_chunk(chunk: str) -> str:
    lines = chunk.replace("\r\n", "\n").split("\n")
    cleaned = []
    for ln in lines:
        if FENCE_OPEN_RE.match(ln) or FENCE_ANY_RE.fullmatch(ln) or LANG_LINE_RE.match(ln):
            continue
        cleaned.append(ln)
    chunk = "\n".join(cleaned)
    chunk = FENCE_ANY_RE.sub("", chunk)
    return chunk

def ollama_chat_stream(messages, model: str):
    url_chat = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
    payload_chat = {"model": model, "messages": messages, "stream": True,
                    "options": {"temperature": TEMPERATURE}}
    try:
        with requests.post(url_chat, json=payload_chat, stream=True, timeout=TIMEOUT) as r:
            if r.status_code == 404:
                raise requests.HTTPError("404 chat", response=r)
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line: continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    m = re.match(r"^data:\s*(\{.*\})\s*$", line)
                    if not m: continue
                    try: obj = json.loads(m.group(1))
                    except Exception: continue
                if "message" in obj and "content" in obj["message"]:
                    yield sanitize_stream_chunk(obj["message"]["content"])
                if obj.get("done"): break
            return
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 404: raise

    # Fallback /api/generate
    def join_messages(msgs):
        chunks = []
        for m in msgs:
            role = m.get("role", "user").upper()
            content = m.get("content", "")
            chunks.append(f"{role}:\n{content}\n")
        chunks.append("ASSISTANT:\n")
        return "\n".join(chunks)

    url_gen = f"{OLLAMA_HOST.rstrip('/')}/api/generate"
    prompt = join_messages(messages)
    payload_gen = {"model": model, "prompt": prompt, "stream": True, "options": {"temperature": TEMPERATURE}}
    with requests.post(url_gen, json=payload_gen, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line: continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            piece = obj.get("response")
            if piece: yield sanitize_stream_chunk(piece)
            if obj.get("done"): break

# -------------------- HTML helpers (no necesitamos regenerar) --------------------
HTML_HEAD_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="{assets_rel}/present.css" rel="stylesheet">
</head>
<body class="brand ceacfp">
  <main id="deck" tabindex="0" aria-live="polite">
"""

HTML_FOOT_TEMPLATE = """
  </main>
  <footer class="footer">
    <div class="meta"></div>
    <div class="controls" aria-label="Controles de zoom">
      <button id="zoomOut" title="Zoom - (tecla -)">−</button>
      <button id="zoomReset" title="Zoom 100% (tecla 0)"><span id="zoomPct">100%</span></button>
      <button id="zoomIn" title="Zoom + (tecla +)">+</button>
      <!-- FS button se inyecta por JS si falta -->
    </div>
    <!-- Progreso será movido fuera por JS si está aquí -->
    <div class="progress" aria-label="Progreso de la presentación" aria-live="off">
      <div class="bar" id="progressBar" style="width:0%"></div>
    </div>
  </footer>
  <script src="{assets_rel}/present.js"></script>
</body>
</html>
"""

def write_html_header(fh, title: str, assets_rel: str):
    write_stream(fh, HTML_HEAD_TEMPLATE.format(title=title, assets_rel=assets_rel))

def write_html_footer(fh, doc_name: str, unit_title: str, subunit_title: str, model: str, assets_rel: str):
    # metadata se imprime en consola/JS; el HTML puede ser antiguo
    write_stream(fh, HTML_FOOT_TEMPLATE)

def open_slide(fh, data_id: str):
    write_stream(fh, f'\n<section class="slide" data-id="{data_id}">\n')
    write_stream(fh, '<div class="fp-badge">FP OFICIAL</div>\n')

def close_slide(fh):
    write_stream(fh, "\n</section>\n")

# -------------------- Assets (CSS/JS) --------------------
def ensure_assets(base_outdir: Path):
    assets = base_outdir / "present-assets"
    assets.mkdir(parents=True, exist_ok=True)
    css = assets / "present.css"
    js = assets / "present.js"
    logo = assets / BRAND_LOGO_FILENAME

    if not logo.exists():
        logo.write_text(
            f"""<svg xmlns='http://www.w3.org/2000/svg' width='320' height='80' viewBox='0 0 320 80'>
  <rect width='320' height='80' fill='{BRAND_PRIMARY}'/>
  <text x='24' y='52' font-family='Segoe UI, Calibri, Arial, sans-serif' font-size='34' fill='white' font-weight='700'>{BRAND_NAME}</text>
</svg>""",
            encoding="utf-8"
        )

    css_content = f"""/* present.css — Reflow zoom + FS, compatible con HTML antiguo */
:root {{
  --bg: {BRAND_BG};
  --fg: {BRAND_TEXT};
  --muted: {BRAND_MUTED};
  --primary: {BRAND_PRIMARY};
  --accent: {BRAND_ACCENT};
  --card: #FAFAFA;
  --fs: 16px;               /* << base font-size para zoom reflow */
  --logo-url: url('{BRAND_LOGO_FILENAME}');
}}
*{{box-sizing:border-box}}
html {{ height:100%; font-size: var(--fs); }}  /* << rem se basa en esto */
body {{
  height:100%;
  margin:0; background:var(--bg); color:var(--fg);
  font-family:{BRAND_FONT_STACK};
  line-height:1.5;
  overflow:hidden;  /* pantalla completa sin scroll de página */
}}
main#deck {{
  width:100%; height:100%; overflow:hidden; margin:0; padding:0;
}}
.slide {{
  display:none; width:100%; height:100%; position:relative;
  padding: 4.5rem 3rem 3rem;  /* usa rems => reflow al hacer zoom */
  background:linear-gradient(180deg, #FFFFFF, var(--card));
  border:0; box-shadow:none; border-radius:0;
}}
.slide.active{{display:block}}
.slide::before {{
  content:""; position:absolute; left:0; top:0; right:0; height:3.5rem;
  background:linear-gradient(90deg, var(--primary) 0%, var(--accent) 100%);
}}
.slide::after {{
  content:""; position:absolute; left:1.2rem; top:.6rem; width:12.5rem; height:2.3rem;
  background-image:var(--logo-url); background-repeat:no-repeat; background-size:contain; background-position:left center;
}}
.slide .fp-badge {{
  position:absolute; right:1.2rem; top:.8rem;
  background:rgba(255,255,255,.92); color:#111827; border:1px solid rgba(0,0,0,.08);
  padding:.25rem .5rem; border-radius:999px; font-weight:700; font-size:.8rem;
}}
h1,h2,h3{{ margin:0 0 .75rem; line-height:1.2; font-weight:700; color:#0B1220 }}
h1{{ font-size:2.4rem }} h2{{ font-size:1.6rem }} h3{{ font-size:1.2rem; color:#111827 }}
p{{ margin:.5rem 0 1rem; font-size:1.08rem; word-wrap:break-word; overflow-wrap:break-word; }}
ul{{ padding-left:1.2rem }} li{{ margin:.4rem 0; font-size:1.08rem }}
a{{ color:var(--primary); text-decoration:none }} a:hover{{ text-decoration:underline }}
code,pre{{ background:#F3F4F6; border:1px solid #E5E7EB; padding:.2rem .4rem; border-radius:6px }}
section.slide > *:last-child{{ margin-bottom:0 }}

/* Footer existente (HTML viejo) */
.footer {{
  position:fixed; left:0; right:0; bottom:.5rem;
  display:flex; align-items:center; gap:.75rem; flex-wrap:wrap;
  padding:.6rem 1rem; color:#374151; font-size:.92rem;
  background:rgba(255,255,255,.95); border-top:1px solid #E5E7EB; backdrop-filter:saturate(120%) blur(6px);
  z-index: 9998; /* por encima de progreso */
}}
.footer .meta{{ flex:1 1 auto; min-width:260px }}
.footer .controls{{ display:flex; gap:.5rem; align-items:center }}
.footer .controls button{{
  appearance:none; border:1px solid #D1D5DB; background:#FFFFFF; color:#111827;
  border-radius:10px; padding:.25rem .6rem; font-weight:600; cursor:pointer;
}}
.footer .controls button:hover{{ border-color:#9CA3AF }}
#zoomPct{{ display:inline-block; min-width:3.5ch; text-align:center }}

/* Progreso fijo, independiente del zoom (si no existe, JS lo crea) */
.progress {{
  position:fixed; left:0; right:0; bottom:3.5rem;
  height:.38rem; background:#E5E7EB; overflow:hidden;
  z-index: 9999;  /* por encima de todo */
}}
.progress .bar{{ height:100%; width:0%; background:var(--accent); transition:width .2s ease; }}

/* Fullscreen: oculta footer; progreso pegado a abajo */
.is-fullscreen .footer{{ display:none !important; }}
.is-fullscreen .progress{{ bottom:0; }}

/* Impresión A4 apaisado con reflow */
@media print{{
  @page{{ size:A4 landscape; margin:10mm; }}
  html, body{{ height:auto; overflow:visible; background:#fff !important; color:#000 !important; }}
  main#deck{{ width:100%; height:auto !important; overflow:visible !important; padding:0; margin:0; }}
  .slide{{
    display:block !important; width:100%;
    height:auto !important; background:#fff !important; color:#000 !important;
    border:0 !important; border-radius:0 !important; box-shadow:none !important;
    padding:28pt 22pt 16pt 22pt !important; page-break-after:always; break-after:page;
  }}
  .slide::before{{ height:28pt; background:linear-gradient(90deg, {BRAND_PRIMARY} 0%, {BRAND_ACCENT} 100%); }}
  .slide::after{{ top:6pt; left:10pt; width:120pt; height:20pt; background-image:var(--logo-url); }}
  .slide .fp-badge{{
    right:10pt; top:8pt; border:1px solid #e5e7eb; background:#fff; color:#000;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  h1{{ font-size:18pt !important; margin:6pt 0 8pt !important }}
  h2{{ font-size:14pt !important; margin:4pt 0 6pt !important }}
  h3{{ font-size:12pt !important; margin:2pt 0 4pt !important }}
  p, li{{ font-size:11pt !important; color:#000 !important }}
  ul{{ padding-left:18pt !important }}
  .footer, .progress{{ display:none !important }}
}}
"""

    js_content = r"""(function(){
  const deck = document.getElementById('deck');
  if(!deck) return;
  const slides = Array.from(deck.querySelectorAll('.slide'));
  let idx = 0;

  /* Ensure PROGRESS exists & is OUTSIDE the footer */
  let progress = document.querySelector('.progress');
  const footer = document.querySelector('.footer');

  if(!progress){
    progress = document.createElement('div');
    progress.className = 'progress';
    const bar = document.createElement('div');
    bar.className = 'bar'; bar.id = 'progressBar';
    progress.appendChild(bar);
    (footer ? document.body.insertBefore(progress, footer) : document.body.appendChild(progress));
  }else{
    if(footer && progress.parentElement === footer){
      document.body.insertBefore(progress, footer);
    }
    if(!progress.querySelector('#progressBar')){
      const bar = document.createElement('div');
      bar.className = 'bar'; bar.id = 'progressBar';
      progress.appendChild(bar);
    }
  }
  const bar = document.getElementById('progressBar');

  function updateProgress(){
    if(!bar||slides.length===0) return;
    const pct = Math.round(((idx+1)/slides.length)*100);
    bar.style.width = pct+'%';
  }

  /* === ZOOM (reflow): cambia font-size raíz mediante --fs === */
  const BASE_FS = 16;                 // px
  const ZMIN=0.5, ZMAX=2.0, ZSTEP=0.1;
  let zoom = 1.0;

  const zoomPctEl = document.getElementById('zoomPct');
  const btnIn = document.getElementById('zoomIn');
  const btnOut = document.getElementById('zoomOut');
  const btnReset = document.getElementById('zoomReset');

  function clamp(n,a,b){return Math.min(b,Math.max(a,n));}
  function applyZoom(){
    const px = Math.max(10, Math.round(BASE_FS * zoom));
    document.documentElement.style.setProperty('--fs', px + 'px'); // reflow!
    if(zoomPctEl) zoomPctEl.textContent = Math.round(zoom*100)+'%';
  }
  function setZoomValue(z){ zoom = clamp(+z.toFixed(2), ZMIN, ZMAX); applyZoom(); }
  function zoomIn(){ setZoomValue(zoom+ZSTEP); }
  function zoomOut(){ setZoomValue(zoom-ZSTEP); }
  function zoomReset(){ setZoomValue(1.0); }

  if(btnIn) btnIn.addEventListener('click', zoomIn);
  if(btnOut) btnOut.addEventListener('click', zoomOut);
  if(btnReset) btnReset.addEventListener('click', zoomReset);

  /* === NAVIGATION === */
  function show(i){
    if(slides.length===0) return;
    idx=(i+slides.length)%slides.length;
    slides.forEach((s,k)=>s.classList.toggle('active',k===idx));
    const id=slides[idx].getAttribute('data-id')||String(idx+1);
    history.replaceState(null,'','#'+encodeURIComponent(id));
    deck.focus({preventScroll:true});
    updateProgress();
  }
  const initialHash=decodeURIComponent((location.hash||'').replace(/^#/,''));
  const initialIndex=slides.findIndex(s=>(s.getAttribute('data-id')||'')===initialHash);
  show(initialIndex>=0?initialIndex:0);
  applyZoom(); // set initial --fs

  function next(){ show(idx+1); } function prev(){ show(idx-1); }
  window.addEventListener('keydown', (e)=>{
    if(e.key==='ArrowRight'||e.key==='PageDown'||e.key===' '){ e.preventDefault(); next(); }
    if(e.key==='ArrowLeft'||e.key==='PageUp'||e.key==='Backspace'){ e.preventDefault(); prev(); }
    if(e.key==='Home'){ e.preventDefault(); show(0); }
    if(e.key==='End'){ e.preventDefault(); show(slides.length-1); }
    if(e.key==='+'||e.key==='='){ e.preventDefault(); zoomIn(); }
    if(e.key==='-'){ e.preventDefault(); zoomOut(); }
    if(e.key==='0'){ e.preventDefault(); zoomReset(); }
    if(e.key.toLowerCase()==='f'){ e.preventDefault(); toggleFullscreen(); }
  });

  deck.addEventListener('click',(e)=>{
    const rect=deck.getBoundingClientRect();
    const x=e.clientX-rect.left;
    if(x>rect.width/2) next(); else prev();
  },false);
  let sx=null; deck.addEventListener('touchstart', e=>{ sx=e.touches[0].clientX; }, {passive:true});
  deck.addEventListener('touchend', e=>{ if(sx==null) return; const dx=(e.changedTouches[0].clientX - sx); if(Math.abs(dx)>40){ if(dx<0) next(); else prev(); } sx=null; }, {passive:true});

  /* === FULLSCREEN: inyecta botón si falta, y alterna clase para CSS === */
  const controls = footer ? footer.querySelector('.controls') : null;
  let fsBtn = document.getElementById('fsToggle');
  if(!fsBtn && controls){
    fsBtn = document.createElement('button');
    fsBtn.id = 'fsToggle';
    fsBtn.title = 'Pantalla completa (tecla F)';
    fsBtn.textContent = '⛶';
    controls.appendChild(fsBtn);
  }
  function isFs(){ return document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement; }
  function reqFs(el){ if(el.requestFullscreen) return el.requestFullscreen(); if(el.webkitRequestFullscreen) return el.webkitRequestFullscreen(); if(el.mozRequestFullScreen) return el.mozRequestFullScreen(); if(el.msRequestFullscreen) return el.msRequestFullscreen(); }
  function exitFs(){ if(document.exitFullscreen) return document.exitFullscreen(); if(document.webkitExitFullscreen) return document.webkitExitFullscreen(); if(document.mozCancelFullScreen) return document.mozCancelFullScreen(); if(document.msExitFullscreen) return document.msExitFullscreen(); }
  function toggleFullscreen(){ if(isFs()) exitFs(); else reqFs(document.documentElement); }
  function onFsChange(){
    const fs = !!isFs();
    document.body.classList.toggle('is-fullscreen', fs);
    if(fsBtn) fsBtn.textContent = fs ? '⤢' : '⛶';
  }
  if(fsBtn) fsBtn.addEventListener('click', toggleFullscreen);
  document.addEventListener('fullscreenchange', onFsChange);
  document.addEventListener('webkitfullscreenchange', onFsChange);
  document.addEventListener('mozfullscreenchange', onFsChange);
  document.addEventListener('MSFullscreenChange', onFsChange);
})();"""

    if FORCE_ASSET_OVERWRITE or not css.exists():
        css.write_text(css_content, encoding="utf-8")
    if FORCE_ASSET_OVERWRITE or not js.exists():
        js.write_text(js_content, encoding="utf-8")

    return assets

# -------------------- Slides extra --------------------
EXTRA_TEMPLATES = [
    ("Conceptos clave (ampliación)", lambda t: f"<p>Profundiza en los fundamentos de <strong>{t}</strong> con definiciones operativas y límites de aplicación.</p><ul><li>Concepto A vs B</li><li>Variables implicadas</li><li>Supuestos habituales</li><li>Cuándo NO aplicar</li></ul>"),
    ("Ejemplo aplicado",            lambda t: f"<p>Ejemplo paso a paso de <strong>{t}</strong> en un escenario realista.</p><ol><li>Contexto</li><li>Decisiones clave</li><li>Resultado</li><li>Métricas</li><li>Mejoras</li></ol>"),
    ("Buenas prácticas",            lambda t: f"<ul><li>Estándar recomendado para {t}</li><li>Checklist previo</li><li>Métricas de calidad</li><li>Patrones reutilizables</li></ul>"),
    ("Errores comunes",             lambda t: f"<ul><li>Confundir objetivos</li><li>Omitir validación</li><li>Falta de trazabilidad</li><li>Fuentes no verificadas</li><li>Prevención</li></ul>"),
    ("Flujo de trabajo",            lambda t: f"<ol><li>Entrada</li><li>Procesamiento</li><li>Validación</li><li>Entrega</li></ol><p>Roles y puntos de control.</p>"),
    ("Comparativa",                 lambda t: f"<p>Comparación de alternativas relacionadas con <strong>{t}</strong>.</p><ul><li>Opción 1 — pros/contras</li><li>Opción 2 — pros/contras</li><li>Recomendación</li></ul>"),
    ("Mini-quiz",                   lambda t: f"<p>Responde mentalmente:</p><ol><li>¿Qué indicador valida {t}?</li><li>¿Qué harías si falla X?</li><li>¿Diferencia entre A y B?</li></ol>"),
    ("Checklist",                   lambda t: f"<ul><li>[ ] Objetivo definido</li><li>[ ] Datos disponibles</li><li>[ ] Criterios de calidad</li><li>[ ] Riesgos evaluados</li><li>[ ] Aprobación</li></ul>"),
    ("Actividad guiada",            lambda t: f"<p>Actividad en parejas sobre <strong>{t}</strong>:</p><ol><li>Analiza un caso breve</li><li>Propón 2 mejoras</li><li>Sintetiza en 10 líneas</li></ol>"),
    ("Resumen y próximos pasos",    lambda t: f"<ul><li>Esenciales</li><li>Herramientas</li><li>Prácticas</li><li>Lecturas</li></ul>"),
]

def write_extra_slides(out, needed: int, subunit_title: str, subtopics: List[str]):
    anchor = subtopics[0] if subtopics else subunit_title
    idx = 0
    while needed > 0:
        title, maker = EXTRA_TEMPLATES[idx % len(EXTRA_TEMPLATES)]
        open_slide(out, data_id=slugify(f"extra-{title}-{idx}"))
        write_stream(out, f"<h2>{title}</h2>\n")
        write_stream(out, maker(anchor) + "\n")
        close_slide(out)
        needed -= 1
        idx += 1

# -------------------- generación de presentaciones --------------------
def process_subunit_to_html(out_html: Path, assets_rel: str, doc_name: str,
                            unit_title: str, subunit_title: str, subtopics: List[str],
                            model: str, base_messages: List[Dict]):
    if out_html.exists():
        print(f"    [SKIP] Ya existe: {out_html.name} (no se sobrescribe)")
        return

    title = f"{subunit_title} — {unit_title} — {doc_name}"
    with out_html.open("w", encoding="utf-8") as out:
        # header mínimo (viejos HTML seguirán funcionando con assets nuevos)
        write_html_header(out, title, assets_rel)
        open_slide(out, data_id=slugify(subunit_title) or "portada")
        write_stream(out, f"<h1>{subunit_title}</h1>\n")
        write_stream(out, f"<p><strong>Unidad:</strong> {unit_title}<br><strong>Documento:</strong> {doc_name}</p>\n")
        write_stream(out, "<p>Objetivos: comprender los conceptos clave y su aplicación práctica.</p>")
        close_slide(out)

        prompt = make_subunit_prompt(doc_name, unit_title, subunit_title, subtopics)
        messages = base_messages + [{"role": "user", "content": prompt}]

        slide_count = 1
        try:
            for chunk in ollama_chat_stream(messages, model=model):
                if not chunk: continue
                slide_count += len(re.findall(r"<\s*section\b", chunk, flags=re.IGNORECASE))
                write_stream(out, chunk)
        except Exception as e:
            open_slide(out, data_id="error")
            write_stream(out, f"<h2>Error</h2><p>{e}</p>")
            close_slide(out)

        if slide_count == 1:
            open_slide(out, data_id="contenido")
            write_stream(out, "<h2>Contenido</h2>\n")
            if subtopics:
                write_stream(out, "<ul>\n")
                for t in subtopics: write_stream(out, f"  <li>{t}</li>\n")
                write_stream(out, "</ul>\n")
            else:
                write_stream(out, "<p>Esta subunidad no detalla subtemas específicos.</p>\n")
            close_slide(out)
            slide_count += 1

        if slide_count < MIN_SLIDES:
            write_extra_slides(out, MIN_SLIDES - slide_count, subunit_title, subtopics)

        write_html_footer(out, doc_name, unit_title, subunit_title, model=model, assets_rel=assets_rel)

# -------------------- INDEX BUILDERS --------------------
def write_index(outdir: Path, index_data: List[Dict]):
    index_path = outdir / "index.html"
    head = """<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><title>Índice de presentaciones</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#fff;--fg:#111827;--muted:#6b7280;--accent:%s}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 %s}
.wrap{max-width:1100px;margin:0 auto;padding:2rem} h1{font-size:2rem;margin:0 0 1rem}
h2{font-size:1.2rem;margin:1.5rem 0 .5rem;color:var(--accent)}
details{background:#fff;margin:.5rem 0;border-radius:12px;padding:1rem;border:1px solid #e5e7eb;box-shadow:0 4px 14px rgba(0,0,0,.04)}
summary{cursor:pointer;font-weight:700} ul{margin:.5rem 0 0 1rem}
a{color:#1d4ed8;text-decoration:none} a:hover{text-decoration:underline}
.doc{margin:1rem 0 2rem} .meta{color:var(--muted);font-size:.9rem;margin:.5rem 0 1rem}
@media print{ body{background:#fff;color:#000} .wrap{max-width:100%;padding:0} a{color:#000;text-decoration:underline} }
</style></head><body><div class="wrap">
<h1>Índice de presentaciones (global)</h1>
<p class="meta">Generado: """ % (BRAND_ACCENT, BRAND_FONT_STACK) + time.strftime('%Y-%m-%d %H:%M:%S') + """</p>
"""
    foot = "</div></body></html>"
    with index_path.open("w", encoding="utf-8") as f:
        f.write(head)
        for doc in index_data:
            rel_doc_dir = os.path.relpath(doc["doc_dir"], outdir)
            per_doc_index = f"{rel_doc_dir}/index.html"
            f.write(f'<div class="doc">\n<h2>Documento: <a href="{per_doc_index}">{doc["doc_name"]}</a></h2>\n')
            for unit in doc["units"]:
                f.write('<details open>\n  <summary>' + unit["unit_title"] + '</summary>\n  <ul>\n')
                for it in unit["items"]:
                    href = f'{rel_doc_dir}/{it["html_name"]}'
                    f.write(f'    <li><a href="{href}">{it["subunit_title"]}</a></li>\n')
                f.write('  </ul>\n</details>\n')
            f.write('</div>\n')
        f.write(foot)

def write_doc_index(doc_outdir: Path, doc_name: str, units: List[Dict], root_outdir: Path):
    index_path = doc_outdir / "index.html"
    rel_root_index = os.path.relpath(root_outdir / "index.html", doc_outdir)
    head = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><title>Índice — {doc_name}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{{--bg:#fff;--fg:#111827;--muted:#6b7280;--accent:{BRAND_ACCENT}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 {BRAND_FONT_STACK}}}
.wrap{{max-width:1100px;margin:0 auto;padding:2rem}} h1{{font-size:2rem;margin:0 0 1rem}}
h2{{font-size:1.2rem;margin:1.5rem 0 .5rem;color:var(--accent)}}
details{{background:#fff;margin:.5rem 0;border-radius:12px;padding:1rem;border:1px solid #e5e7eb;box-shadow:0 4px 14px rgba(0,0,0,.04)}}
summary{{cursor:pointer;font-weight:700}} ul{{margin:.5rem 0 0 1rem}}
a{{color:#1d4ed8;text-decoration:none}} a:hover{{text-decoration:underline}}
.meta{{color:var(--muted);font-size:.9rem;margin:.25rem 0 1rem}}
@media print{{ body{{background:#fff;color:#000}} .wrap{{max-width:100%;padding:0}} a{{color:#000;text-decoration:underline}} }}
</style></head><body><div class="wrap">
<div class="breadcrumb"><a href="{rel_root_index}">← Volver al índice global</a></div>
<h1>Índice — {doc_name}</h1>
<p class="meta">Generado: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
"""
    foot = "</div></body></html>"
    with index_path.open("w", encoding="utf-8") as f:
        f.write(head)
        for unit in units:
            f.write('<details open>\n  <summary>' + unit["unit_title"] + '</summary>\n')
            f.write('  <ul>\n')
            for it in unit["items"]:
                href = it["html_name"]
                f.write(f'    <li><a href="{href}">{it["subunit_title"]}</a></li>\n')
            f.write('  </ul>\n</details>\n')
        f.write(foot)

# -------------------- procesamiento principal --------------------
def main():
    parser = argparse.ArgumentParser(description="Generador de presentaciones HTML por subunidad desde .md usando Ollama")
    parser.add_argument("--list-models", action="store_true", help="Lista los modelos disponibles y sale")
    parser.add_argument("--model", help="Nombre exacto del modelo Ollama a usar")
    parser.add_argument("--dir", default=".", help="Directorio con los .md")
    parser.add_argument("--outdir", default="./presentations", help="Directorio de salida")
    args = parser.parse_args()

    try:
        models = list_models_http()
    except Exception:
        models = list_models_cli()

    if args.list_models:
        if not models:
            print("No se han encontrado modelos. Prueba:  ollama pull llama3.1:8b-instruct")
        else:
            print("Modelos disponibles en Ollama:"); [print(" -", m) for m in models]
        return

    if args.model:
        model = args.model
        if models and model not in models:
            print(f"[ADVERTENCIA] El modelo '{model}' no aparece en la lista, intentando igualmente...")
    else:
        if not models:
            raise SystemExit("No hay modelos disponibles. Instala alguno con: ollama pull llama3.1:8b-instruct")
        model = auto_pick_model(models)
        print(f"[INFO] Modelo seleccionado automáticamente: {model}")

    base = Path(args.dir).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    assets_dir = ensure_assets(outdir)

    md_files = list_pure_md_files(base)
    if not md_files:
        print("No se han encontrado archivos .md (puros) en este directorio.")
        print("Nota: los archivos que terminan en '.doc.md' se excluyen automáticamente.")
        return

    print(f"[INFO] Construyendo contexto global con {len(md_files)} archivo(s)...")
    project_ctx = build_project_context(md_files)

    base_messages = [
        {"role": "system",
         "content": ("Eres un asistente experto en documentación técnica y académica en español. "
                     "Generarás presentaciones HTML didácticas por subunidad, con variedad de slides y rigor.")},
        {"role": "user", "content": project_ctx},
        {"role": "assistant", "content": "Contexto comprendido. Listo para generar presentaciones por subunidad."}
    ]

    index_data: List[Dict] = []

    for md_path in md_files:
        doc_name = md_path.name
        print(f"[INFO] Analizando {doc_name} ...")
        lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=False)
        structure = parse_units_and_subunits(lines)

        # Subcarpeta por documento
        doc_outdir = outdir / slugify(doc_name.replace(".md", ""))
        doc_outdir.mkdir(parents=True, exist_ok=True)
        assets_rel = os.path.relpath(assets_dir, doc_outdir)

        index_doc = {"doc_name": doc_name, "doc_dir": doc_outdir, "units": []}

        total_subunits = 0
        for u_idx, unit in enumerate(structure, start=1):
            unit_title = unit["unit_title"] or f"Unidad {u_idx}"
            unit_slug = f"{u_idx:02d}-{slugify(unit_title)}"
            unit_items = []

            for s_idx, sub in enumerate(unit.get("subunits", []), start=1):
                subunit_title = sub["subunit_title"] or f"Subunidad {u_idx}.{s_idx}"
                subtopics = sub.get("subtopics", [])
                total_subunits += 1

                sub_slug  = f"{s_idx:02d}-{slugify(subunit_title)}"
                out_html = doc_outdir / f"{unit_slug}__{sub_slug}.{model.replace(':','_')}.html"

                if out_html.exists():
                    print(f"  - Saltando (ya existe): {out_html.name}")
                else:
                    print(f"  - Generando presentación: {out_html.name}")
                    process_subunit_to_html(
                        out_html=out_html,
                        assets_rel=assets_rel,
                        doc_name=doc_name,
                        unit_title=unit_title,
                        subunit_title=subunit_title,
                        subtopics=subtopics,
                        model=model,
                        base_messages=base_messages
                    )
                unit_items.append({"subunit_title": subunit_title, "html_name": out_html.name})

            index_doc["units"].append({"unit_title": unit_title, "items": unit_items})

        index_data.append(index_doc)
        print(f"[DONE] {doc_name}: {total_subunits} presentaciones (nuevas o existentes) en {doc_outdir}")

        write_doc_index(doc_outdir=doc_outdir, doc_name=doc_name,
                        units=index_doc["units"], root_outdir=outdir)

    write_index(outdir, index_data)
    print(f"[OK] Índice global generado en: {outdir / 'index.html'}")

if __name__ == "__main__":
    main()


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doc_md_ollama_stream.py
- Listado de modelos (--list-models)
- Selección de modelo (--model NOMBRE) o autodetección
- Streaming real a disco
- Evita procesar *.doc.md
- Compatibilidad: /api/chat (nuevo) o /api/generate (fallback) si tu Ollama no lo soporta (404)
"""

import os
import re
import json
import time
import textwrap
import argparse
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional

import requests

# ========================= CONFIG PREDETERMINADA =========================
DEFAULT_PREFERRED = [
    "llama3.1:8b-instruct",
    "gemma2:9b-instruct",
    "qwen2.5:7b-instruct",
    "qwen2.5-coder:7b",
    "gpt-oss:20b",
]

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0.2"))
TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))

MAX_FILES = None              # None = todos | número para limitar
MAX_BYTES_PER_FILE = 4000     # extracto por archivo para el contexto global

# ¡IMPORTANTE! No procesar archivos generados:
EXCLUDE_PATTERNS = [
    r"\.doc\.md$",           # cualquier *.doc.md
    r"^README\.md$",         # ejemplo de exclusión opcional
]
# ========================================================================


# -------------------- utilidades modelos --------------------

def list_models_http(host: str = OLLAMA_HOST) -> List[str]:
    """Intenta listar modelos vía HTTP GET /api/tags (Ollama >= 0.1.x)."""
    url = f"{host.rstrip('/')}/api/tags"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    models = []
    # Formato típico: {"models":[{"name":"llama3.1:8b-instruct", ...}, ...]}
    for m in data.get("models", []):
        name = m.get("name")
        if name:
            models.append(name)
    return sorted(set(models))

def list_models_cli() -> List[str]:
    """Fallback: usa 'ollama list' si el HTTP falla."""
    try:
        out = subprocess.check_output(["ollama", "list"], text=True, timeout=5)
    except Exception:
        return []
    models = []
    # Salida típica:
    # NAME                                  ID              SIZE      MODIFIED
    # llama3.1:8b-instruct                  ...             4.2GB     ...
    for line in out.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("name"):
            continue
        # primer token hasta espacios es el nombre
        name = line.split()[0]
        # filtra cosas raras
        if ":" in name or name.isascii():
            models.append(name)
    return sorted(set(models))

def auto_pick_model(available: list[str]) -> str | None:
    """
    Elige el mejor modelo disponible según DEFAULT_PREFERRED.
    1) Match exacto.
    2) Match por prefijo (acepta sufijos como -q4_0, -q5_1, -f16, etc.).
    3) Si hay múltiples coincidencias por prefijo para una misma preferencia,
       prioriza las que contengan 'instruct' y, en igualdad, la más corta (menos sufijos).
    4) Si nada coincide, devuelve el primero disponible.
    """
    if not available:
        return None

    # 1) Exacto
    for pref in DEFAULT_PREFERRED:
        if pref in available:
            return pref

    # 2) Prefijo (permitir sufijos como -q4_0, -q8_0...)
    def best_prefix_match(pref: str) -> str | None:
        candidates = [m for m in available if m.startswith(pref)]
        if not candidates:
            return None
        # prioriza instruct y el nombre más corto (menos adornos)
        candidates.sort(key=lambda n: (0 if "instruct" in n else 1, len(n)))
        return candidates[0]

    for pref in DEFAULT_PREFERRED:
        pick = best_prefix_match(pref)
        if pick:
            return pick

    # 3) Último recurso
    return available[0]


# -------------------- utilidades archivos --------------------

def matches_any_pattern(name: str, patterns: List[str]) -> bool:
    return any(re.search(p, name, flags=re.IGNORECASE) for p in patterns)

def list_pure_md_files(base: Path) -> List[Path]:
    """
    Solo *.md del directorio actual, EXCLUYENDO *.doc.md y lo que encaje en EXCLUDE_PATTERNS.
    """
    files = []
    for p in sorted(base.glob("*.md")):
        if matches_any_pattern(p.name, EXCLUDE_PATTERNS):
            continue
        files.append(p)
    if MAX_FILES:
        files = files[:MAX_FILES]
    return files

def safe_read_text(path: Path, max_bytes: int | None = None) -> str:
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


# -------------------- parsing de líneas --------------------

def detect_level(raw_line: str) -> Tuple[int, str]:
    """
    - Sin '-' ni '·' (y no vacía) => Nivel 1 (tema)
    - Empieza por '-' => Nivel 2
    - Empieza por '·' => Nivel 3
    """
    line = raw_line.rstrip("\n").strip()
    if not line:
        return 0, ""
    if line.startswith("·"):
        return 3, line.lstrip("·").strip()
    if re.match(r"^-+\s*", line):
        clean = re.sub(r"^-+\s*", "", line).strip()
        return 2, clean
    return 1, line

def header_for_level(level: int, text: str) -> str:
    if level == 1: return f"\n### {text}\n"
    if level == 2: return f"\n#### {text}\n"
    if level == 3: return f"\n##### {text}\n"
    return "\n"

def make_line_prompt(level: int, text: str) -> str:
    if level == 1:
        req = "Redacta 1–2 párrafos claros (8–12 frases en total)."
    elif level == 2:
        req = "Redacta 1 párrafo (4–7 frases) o 4–6 viñetas."
    else:
        req = "Redacta 3–5 frases concisas o 3–5 viñetas."
    return textwrap.dedent(f"""\
    Aporta documentación en español para el siguiente epígrafe del temario.
    NO repitas el epígrafe literalmente ni introduzcas encabezados extra.

    Epígrafe: "{text}"

    Requisitos:
    - Tono didáctico, preciso y profesional.
    - Incluye definiciones, objetivos, ejemplos prácticos y matices comunes.
    - Si procede, menciona normativa española aplicable de forma general.
    - {req}
    """)


# -------------------- cliente Ollama con fallback --------------------

def write_stream(fh, text: str):
    fh.write(text)
    fh.flush()
    os.fsync(fh.fileno())

def ollama_chat_stream(messages, model: str) -> str:
    """
    Devuelve un generador de chunks. Intenta /api/chat; si 404, hace fallback a /api/generate.
    """
    # 1) Intento /api/chat
    url_chat = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
    payload_chat = {"model": model, "messages": messages, "stream": True,
                    "options": {"temperature": TEMPERATURE}}
    try:
        with requests.post(url_chat, json=payload_chat, stream=True, timeout=TIMEOUT) as r:
            if r.status_code == 404:
                raise requests.HTTPError("404 chat", response=r)
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    m = re.match(r"^data:\s*(\{.*\})\s*$", line)
                    if not m:
                        continue
                    try:
                        obj = json.loads(m.group(1))
                    except Exception:
                        continue
                if "message" in obj and "content" in obj["message"]:
                    yield obj["message"]["content"]
                if obj.get("done"):
                    break
            return
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 404:
            # Error distinto a 404 → propaga
            raise

    # 2) Fallback /api/generate (Ollama legacy)
    # Unimos mensajes en un "prompt" (estilo sencillo: system + user + assistant + user)
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
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            # formato típico: {"response":"texto...","done":false}
            piece = obj.get("response")
            if piece:
                yield piece
            if obj.get("done"):
                break


# -------------------- procesamiento principal --------------------

def process_file_stream(md_path: Path, project_ctx: str, model: str):
    out_suffix = f".{model.replace(':','_')}.doc.md"
    out_path = md_path.with_suffix(md_path.suffix + out_suffix)

    print(f"[INFO] Procesando {md_path.name} → {out_path.name}")
    original_lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=False)

    base_messages = [
        {"role": "system",
         "content": ("Eres un asistente experto en documentación técnica y académica en español. "
                     "Ayuda a documentar un temario punto por punto con rigor y claridad.")},
        {"role": "user", "content": project_ctx},
        {"role": "assistant", "content": "Contexto comprendido. Listo para documentar línea por línea."}
    ]

    processed = 0
    with out_path.open("w", encoding="utf-8") as out:
        write_stream(out, f"# Documentación generada · {md_path.name}\n")
        write_stream(out, f"_Modelo_: `{model}` · _Fecha_: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n")

        for raw in original_lines:
            level, text = detect_level(raw)
            if level == 0:
                write_stream(out, "\n")
                continue

            write_stream(out, header_for_level(level, text))
            write_stream(out, f"> {raw.strip()}\n\n")
            write_stream(out, "📝 ")

            line_prompt = make_line_prompt(level, text)
            messages = base_messages + [{"role": "user", "content": line_prompt}]

            try:
                for chunk in ollama_chat_stream(messages, model=model):
                    if not chunk:
                        continue
                    write_stream(out, chunk.replace("\r\n", "\n"))
                write_stream(out, "\n\n")
            except requests.HTTPError as e:
                write_stream(out, f"\n\n⚠️ Error HTTP con Ollama: {e}\n\n")
            except requests.RequestException as e:
                write_stream(out, f"\n\n⚠️ Error de red con Ollama: {e}\n\n")
            except Exception as e:
                write_stream(out, f"\n\n⚠️ Error inesperado: {e}\n\n")

            processed += 1
            print(f"  - streamed: {raw.strip()[:80]}{'...' if len(raw.strip())>80 else ''}")

    print(f"[DONE] {md_path.name} → {out_path.name} ({processed} líneas)")


def main():
    parser = argparse.ArgumentParser(description="Documentación en streaming con Ollama sobre archivos .md")
    parser.add_argument("--list-models", action="store_true", help="Lista los modelos disponibles y sale")
    parser.add_argument("--model", help="Nombre exacto del modelo Ollama a usar (p.ej. 'llama3.1:8b-instruct')")
    parser.add_argument("--dir", default=".", help="Directorio con los .md (por defecto, el actual)")
    args = parser.parse_args()

    # Modelos disponibles (HTTP -> CLI)
    try:
        models = list_models_http()
    except Exception:
        models = list_models_cli()

    if args.list_models:
        if not models:
            print("No se han encontrado modelos. Prueba a ejecutar:  ollama pull llama3.1:8b-instruct")
        else:
            print("Modelos disponibles en Ollama:")
            for m in models:
                print(" -", m)
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
    md_files = list_pure_md_files(base)
    if not md_files:
        print("No se han encontrado archivos .md (puros) en este directorio.")
        print("Nota: los archivos que terminan en '.doc.md' se excluyen automáticamente.")
        return

    print(f"[INFO] Construyendo contexto global con {len(md_files)} archivo(s)...")
    project_ctx = build_project_context(md_files)

    for md in md_files:
        process_file_stream(md, project_ctx, model=model)


if __name__ == "__main__":
    main()


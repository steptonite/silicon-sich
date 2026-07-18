#!/bin/bash
# setup.sh — підготовка середовища Second Brain Kit.
# Ідемпотентний: можна ганяти повторно. Нічого не видаляє, лише створює.
#
#   bash scripts/setup.sh
#
# Що робить:
#   1. Перевіряє python3 ≥ 3.11 (потрібен tomllib).
#   2. Створює venv у корені кита + ставить sqlite-vec і numpy.
#   3. Перевіряє Ollama і модель bge-m3 (🙋 якщо нема — каже, що зробити руками).
#   4. Якщо нема config.toml — копіює з config.example.toml і зупиняється
#      (🙋 людина/модель редагує шляхи), інакше:
#   5. Створює теки з конфіга (vault, memory, inbox, tasks, archives, index) і
#      symlinks архівів + memory у vault-корінь (Obsidian бачить один граф).
set -e
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$KIT"

echo "── Second Brain Kit setup ── ($KIT)"

# 1. python ≥ 3.11
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'; then
  echo "❌ Потрібен python3 ≥ 3.11 (tomllib). Встанови новіший Python і повтори."
  exit 1
fi
echo "✅ python3: $(python3 -V)"

# 2. venv + deps
if [ ! -d .venv ]; then
  python3 -m venv .venv
  echo "✅ створено .venv"
fi
.venv/bin/pip install --quiet --upgrade pip sqlite-vec numpy
echo "✅ deps: sqlite-vec ($(.venv/bin/pip show sqlite-vec | grep Version)); numpy"
.venv/bin/python - <<'PY'
import sqlite3

c = sqlite3.connect(":memory:")
if not hasattr(c, "enable_load_extension"):
    raise SystemExit(
        "❌ Ця збірка Python вимикає SQLite extensions, потрібні sqlite-vec. "
        "На macOS встанови актуальний Python через python.org або Homebrew "
        "(рекомендовано 3.13+) і створи .venv заново."
    )
PY

# 3. Embed-рушій (ОПЦІЙНИЙ вибір, див. docs/04-semantics.md):
#    A) OpenRouter — нічого не ставити локально (openrouter_enabled=true + ключ у config)
#    B) локальний Ollama + bge-m3 — $0, приватно
if ! command -v ollama >/dev/null 2>&1; then
  echo "ℹ️ Ollama не знайдено — це ОК, якщо обираєш варіант A (OpenRouter):"
  echo "   у config.toml → [embed] openrouter_enabled = true + ключ OPENROUTER_API_KEY."
  echo "🙋 Якщо хочеш варіант B (локально, \$0, приватно): постав https://ollama.com,"
  echo "   потім 'ollama pull bge-m3' (≈1.1 ГБ) і перезапусти setup.sh."
  echo "   На macOS керувати Ollama-моделями зручно через GUI: https://github.com/steptonite/KobzarAI"
elif ! curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null; then
  echo "🙋 Ollama встановлено, але сервер не відповідає. Запусти застосунок Ollama (або 'ollama serve')."
  echo "   Або обери варіант A (OpenRouter) у config.toml — тоді Ollama не потрібна."
else
  if curl -s http://localhost:11434/api/tags | grep -q "bge-m3"; then
    echo "✅ Ollama живий, bge-m3 на місці"
  else
    echo "→ тягну модель bge-m3 (≈1.1 ГБ, разово)…"
    ollama pull bge-m3
  fi
fi

# 4. config.toml
if [ -n "$SB_CONFIG" ] && [ -f "$SB_CONFIG" ]; then
  echo "✅ конфіг: $SB_CONFIG (з env SB_CONFIG)"
elif [ ! -f scripts/config.toml ]; then
  cp scripts/config.example.toml scripts/config.toml
  echo "🙋 Створено scripts/config.toml з прикладу. Відредагуй шляхи під свою машину"
  echo "   і запусти setup.sh ще раз (створяться теки і symlinks)."
  exit 0
else
  echo "✅ конфіг: scripts/config.toml"
fi

# 5. теки + symlinks з конфіга
.venv/bin/python - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "scripts")  # виконується з кореня кита
from sb_config import CFG, P

root = P(CFG["vault"]["root"])
memory = P(CFG["vault"]["memory"])
inbox = P(CFG["vault"]["inbox"])
tasks = P(CFG["vault"].get("tasks", "~/SecondBrain/tasks"))
db = P(CFG["index"]["db_path"])
for d in (root, memory, inbox, tasks / "active", tasks / "archive", db.parent):
    d.mkdir(parents=True, exist_ok=True)
    print(f"✅ тека: {d}")

def link(target: Path, name: str):
    ln = root / name
    if ln.is_symlink() or ln.exists():
        print(f"   (є) {ln}")
        return
    ln.symlink_to(target)
    print(f"✅ symlink: {ln} → {target}")

# memory та архіви — symlink у vault-корінь, файли фізично лишаються на місцях
if memory.resolve() != (root / "memory").resolve():
    link(memory, "memory")
for key in ("chatgpt", "gemini", "claude", "claude_code", "codex"):
    if key not in CFG["archives"]:
        continue
    arch = P(CFG["archives"][key])
    arch.mkdir(parents=True, exist_ok=True)
    if arch.resolve().parent != root.resolve():
        link(arch, f"{key}-archive")
if tasks.resolve().parent != root.resolve():
    link(tasks, "tasks")
PY

echo "── Готово. Далі за PLAYBOOK.md: конверсія експортів → індексація → хуки. ──"

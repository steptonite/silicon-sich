#!/bin/bash
# setup.sh — підготовка середовища Second Brain Kit.
# Ідемпотентний: можна ганяти повторно. Нічого не видаляє, лише створює.
#
#   bash scripts/setup.sh
#
# Що робить:
#   1. Перевіряє python3 ≥ 3.11 (потрібен tomllib).
#   2. Створює venv у корені кита + ставить sqlite-vec.
#   3. Перевіряє Ollama і модель bge-m3 (🙋 якщо нема — каже, що зробити руками).
#   4. Якщо нема config.toml — копіює з config.example.toml і зупиняється
#      (🙋 людина/модель редагує шляхи), інакше:
#   5. Створює теки з конфіга (vault, memory, inbox, archives, index) і
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
.venv/bin/pip install --quiet --upgrade pip sqlite-vec
echo "✅ deps: sqlite-vec ($(.venv/bin/pip show sqlite-vec | grep Version))"

# 3. Ollama + bge-m3
if ! command -v ollama >/dev/null 2>&1; then
  echo "🙋 Ollama не встановлено. Людина: постав з https://ollama.com і запусти застосунок."
  echo "   Потім: ollama pull bge-m3   (≈1.1 ГБ, разово). І перезапусти setup.sh."
elif ! curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null; then
  echo "🙋 Ollama встановлено, але сервер не відповідає. Запусти застосунок Ollama (або 'ollama serve')."
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
db = P(CFG["index"]["db_path"])
for d in (root, memory, inbox, db.parent):
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
for key in ("chatgpt", "gemini", "claude"):
    arch = P(CFG["archives"][key])
    arch.mkdir(parents=True, exist_ok=True)
    if arch.resolve().parent != root.resolve():
        link(arch, f"{key}-archive")
PY

echo "── Готово. Далі за PLAYBOOK.md: конверсія експортів → індексація → хуки. ──"

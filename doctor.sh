#!/bin/bash
# Second Brain Kit — діагностика встановленої копії.
#
#   bash doctor.sh          перевірити і сказати, що не так
#   bash doctor.sh --fix    полагодити те, що лагодиться безпечно
#
# Навіщо (23.08.2026, після першої чужої установки — 3 години голосом):
# поломок було меншість. Час зʼїли питання «чого система не сказала»: скільки
# коштуватиме дія, який рушій насправді поїде, звідки взявся чужий контекст,
# у якому порядку ставити. setup.sh уміє СТАВИТИ, але нічого не звіряє: він
# кладе заново поверх, і те, що вже поламалось, лишається поламаним.
#
# 🔴 Правило, заради якого це існує: інсталятор, що вміє ставити, і інсталятор,
#    що вміє ЛАГОДИТИ ВСТАНОВЛЕНЕ, — це різні програми. Друга тут.
# 🔴 Друге правило: кожен ✗ дає ОДНУ команду виправлення, а не абзац тексту.
set -uo pipefail

FIX=0
case "${1:-}" in
  --fix) FIX=1 ;;
  -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
  "") ;;
  *) echo "невідомий аргумент: $1 (є --fix, --help)"; exit 2 ;;
esac

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$KIT"

PROBLEMS=0; FIXED=0; NEEDS=""
ok()    { printf '  ✅ %s\n' "$1"; }
warn()  { printf '  ⚠️  %s\n' "$1"; }
bad()   { printf '  🔴 %s\n' "$1"; PROBLEMS=$((PROBLEMS+1)); }
fixed() { printf '  🔧 полагоджено: %s\n' "$1"; FIXED=$((FIXED+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }
need()  { NEEDS="$NEEDS $1"; }
has_need() { case " $NEEDS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

# Рядки «РІВЕНЬ|текст» і «NEED|ключ» від python-зондів рендеряться тут.
# 🔴 Викликати ТІЛЬКИ як `render < <(...)`. Через пайп цикл піде в підоболонку,
#    PROBLEMS і NEEDS загубляться, і --fix мовчки не полагодить нічого.
render() {
  while IFS='|' read -r lvl msg; do
    case "$lvl" in
      OK)   ok   "$msg" ;;
      WARN) warn "$msg" ;;
      BAD)  bad  "$msg" ;;
      NEED) need "$msg" ;;
      HEAD) head_ "$msg" ;;
      *)    [ -n "$lvl$msg" ] && printf '     %s\n' "$lvl$msg" ;;
    esac
  done
}

echo "Second Brain Kit — перевірка встановленої копії"
echo "кіт: $KIT"

# ── 1. Основа: Python, оточення, sqlite-vec ───────────────────────────
head_ "1. Основа"
PY="$KIT/.venv/bin/python"
if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
  ok "системний python3: $(python3 -V 2>&1)"
else
  bad "системний python3 старший за 3.11 (потрібен tomllib) → постав Python 3.13+ з python.org"
fi

if [ -x "$PY" ]; then
  ok "оточення кіта: $("$PY" -V 2>&1)"
else
  bad "немає .venv кіта → bash scripts/setup.sh"
  need venv
fi

# 🔴 Тиха смерть №1 на macOS: збірка Python без SQLite extensions. Все ставиться
#    «успішно», а перший же пошук падає на завантаженні sqlite-vec.
if [ -x "$PY" ]; then
  render < <("$PY" - <<'PY'
import importlib.util, sqlite3, sys
out = []
c = sqlite3.connect(":memory:")
if not hasattr(c, "enable_load_extension"):
    out.append("BAD|ця збірка Python вимикає SQLite extensions → пересобери .venv на Python з python.org/Homebrew")
    out.append("NEED|venv")
else:
    out.append("OK|SQLite extensions увімкнені")
missing = [m for m in ("sqlite_vec", "numpy") if not importlib.util.find_spec(m)]
if missing:
    out.append("BAD|немає модулів: %s → bash scripts/setup.sh" % " ".join(missing))
    out.append("NEED|venv")
else:
    try:
        import sqlite_vec
        c2 = sqlite3.connect(":memory:")
        c2.enable_load_extension(True); sqlite_vec.load(c2); c2.enable_load_extension(False)
        out.append("OK|sqlite-vec завантажується (векторний пошук поїде)")
    except Exception as e:
        out.append("BAD|sqlite-vec не завантажується: %s → bash scripts/setup.sh" % e)
        out.append("NEED|venv")
print("\n".join(out))
PY
)
fi

# ── 2-5. Конфіг, рушій, vault, індекс ─────────────────────────────────
# 🔴 Один зонд, бо всі чотири перевірки читають той самий config.toml.
#    Запускаємо оточенням кіта, якщо воно є; інакше системним python3.
PROBE_PY="$PY"; [ -x "$PROBE_PY" ] || PROBE_PY="$(command -v python3)"

CFG_FILE="$KIT/scripts/config.toml"
head_ "2. Конфіг"
if [ -f "$CFG_FILE" ] || [ -n "${SB_CONFIG:-}" ]; then
  ok "конфіг знайдено: ${SB_CONFIG:-$CFG_FILE}"
  if [ -f "$CFG_FILE" ] && cmp -s "$KIT/scripts/config.example.toml" "$CFG_FILE"; then
    warn "config.toml дослівно дорівнює прикладу — шляхи, схоже, ще не відредаговані"
  fi
else
  bad "нема scripts/config.toml → cp scripts/config.example.toml scripts/config.toml && bash scripts/setup.sh"
  need config
fi

if [ -f "$CFG_FILE" ] || [ -n "${SB_CONFIG:-}" ]; then
  render < <("$PROBE_PY" - "$KIT" <<'PY'
import os, sys, json, sqlite3, urllib.request
from pathlib import Path

kit = Path(sys.argv[1])
sys.path.insert(0, str(kit / "scripts"))
out = []
try:
    from sb_config import CFG, P
except SystemExit as e:
    print("BAD|конфіг не читається: %s" % e); raise SystemExit(0)
except Exception as e:
    print("BAD|конфіг не читається: %s" % e); raise SystemExit(0)

# ── 2. шляхи з конфіга ──
for key in ("root", "memory", "inbox", "tasks"):
    val = CFG["vault"].get(key)
    if not val:
        out.append("WARN|у [vault] нема ключа %s" % key); continue
    p = P(val)
    out.append(("OK|%s: %s" % (key, p)) if p.exists()
               else ("BAD|%s не існує: %s → bash scripts/setup.sh" % (key, p)))
    if not p.exists():
        out.append("NEED|dirs")

print("\n".join(out)); out = []
print("HEAD|3. Рушій семантики")
# ── 3. Рушій семантики: ЯКИЙ САМЕ поїде і чому ──
# 🔴 Найдорожче питання чужої установки: людина не знала, що працює локально,
#    а що піде в мережу за гроші. Кажемо прямо, а не «auto».
emb = CFG.get("embed", {})
or_enabled = bool(emb.get("openrouter_enabled", False))
ollama_url = emb.get("ollama_url", "http://localhost:11434")
model = emb.get("ollama_model", "bge-m3")

alive = False
try:
    with urllib.request.urlopen(ollama_url.rstrip("/") + "/api/tags", timeout=3) as r:
        tags = json.loads(r.read().decode("utf-8"))
        alive = True
except Exception:
    alive = False

has_model = False
if alive:
    names = [m.get("name", "") for m in tags.get("models", [])]
    has_model = any(model in n for n in names)

key = os.environ.get("OPENROUTER_API_KEY", "").strip()
if not key:
    envf = P(emb.get("env_file", "~/.config/second-brain/.env"))
    if envf.exists():
        for line in envf.read_text(errors="replace").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip()
                break

if alive and has_model:
    out.append("OK|ПОЇДЕ ЛОКАЛЬНО: Ollama %s, модель %s — $0, чати не покидають машину" % (ollama_url, model))
elif alive and not has_model:
    out.append("BAD|Ollama живий, але моделі %s нема → ollama pull %s (≈1.1 ГБ)" % (model, model))
    out.append("NEED|bge")
elif or_enabled and key:
    out.append("WARN|ПОЇДЕ В МЕРЕЖУ: OpenRouter (Ollama не відповідає на %s)" % ollama_url)
    out.append("WARN|це платно і твої тексти покидають машину; локально й безкоштовно — підняти Ollama")
elif or_enabled and not key:
    out.append("BAD|обрано OpenRouter, але ключа нема ні в env, ні в %s → поклади рядок OPENROUTER_API_KEY=..." % P(emb.get("env_file", "~/.config/second-brain/.env")))
else:
    out.append("BAD|рушія семантики НЕМА: Ollama мовчить, openrouter_enabled=false → або запусти Ollama, або постав openrouter_enabled = true + ключ")

print("\n".join(out)); out = []
print("HEAD|4. Vault і граф")
# ── 4. Vault: теки, symlinks, обірвані посилання ──
# 🔴 Реальний випадок: vault поїхав на іншу машину через хмарний диск —
#    symlinks не переносяться і перетворюються на биті посилання.
root = P(CFG["vault"]["root"])
if root.exists():
    dangling = [p.name for p in root.iterdir() if p.is_symlink() and not p.resolve().exists()]
    links = [p.name for p in root.iterdir() if p.is_symlink()]
    if dangling:
        out.append("BAD|биті symlinks у vault (%s) — ціль не існує на цій машині → bash scripts/setup.sh" % ", ".join(sorted(dangling)))
        out.append("NEED|dirs")
    elif links:
        out.append("OK|symlinks живі: %s" % ", ".join(sorted(links)))
    else:
        out.append("WARN|у корені vault нема жодного symlink — архіви й memory в граф не заведені → bash scripts/setup.sh")
    mem_index = P(CFG["vault"]["memory"]) / "MEMORY.md"
    out.append("OK|індекс памʼяті на місці: MEMORY.md" if mem_index.exists()
               else "WARN|нема MEMORY.md у теці memory — модель не побачить карту фактів")

print("\n".join(out)); out = []
print("HEAD|5. Індекс")
# ── 5. Індекс ──
db = P(CFG["index"]["db_path"])
if not db.exists():
    out.append("BAD|індексу нема (%s) → семантичний пошук не працює: librarian.py index --source all" % db)
else:
    try:
        c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        per = dict(c.execute("SELECT source, COUNT(*) FROM chunks GROUP BY source").fetchall())
        nfiles = c.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        total = sum(per.values())
        size = db.stat().st_size / 1e6
        if total == 0:
            out.append("BAD|індекс порожній → .venv/bin/python scripts/librarian.py index --source all")
        else:
            out.append("OK|індекс: %d чанків з %d файлів, %.1f МБ (%s)"
                       % (total, nfiles, size, ", ".join("%s:%d" % kv for kv in sorted(per.items()))))
            # відставання: скільки .md у memory ще не в індексі
            memdir = P(CFG["vault"]["memory"])
            if memdir.exists():
                indexed = {r[0] for r in c.execute("SELECT ref FROM files WHERE source='memory'").fetchall()}
                on_disk = {str(p) for p in memdir.glob("*.md")}
                missing = len(on_disk - indexed)
                if missing:
                    out.append("WARN|%d нот памʼяті ще не в індексі — пошук їх не знайде → librarian.py index --source memory" % missing)
                else:
                    out.append("OK|індекс памʼяті не відстає від диска")
        c.close()
    except Exception as e:
        out.append("BAD|індекс не читається: %s" % e)

print("\n".join(out))
PY
)
fi

# ── 6. Хуки ───────────────────────────────────────────────────────────
head_ "6. Хуки Claude Code"
# 🔴 Класична тиха смерть: хук прописаний, але веде на шлях чужої машини.
#    Claude Code мовчки не викликає його — і памʼять просто «не працює».
render < <("$PROBE_PY" - "$KIT" <<'PY'
import json, sys
from pathlib import Path
kit = Path(sys.argv[1])
out = []
st = Path.home() / ".claude" / "settings.json"
if not st.exists():
    out.append("WARN|нема ~/.claude/settings.json — хуки не встановлені (див. scripts/hooks/settings-hooks.example.json)")
else:
    try:
        data = json.loads(st.read_text(errors="replace"))
    except Exception as e:
        out.append("BAD|~/.claude/settings.json не парситься: %s" % e); data = None
    if data is not None:
        hooks = data.get("hooks", {})
        wanted = {
            "SessionStart": "session_start.sh",
            "PreCompact": "pre_compact.sh",
            "UserPromptSubmit": "semantic_recall.py",
            "PostToolUse": "memory_lint.py",
        }
        for event, fname in wanted.items():
            cmds = []
            for group in hooks.get(event, []):
                for h in group.get("hooks", []):
                    cmds.append(h.get("command", ""))
            mine = [c for c in cmds if fname in c]
            if not mine:
                out.append("WARN|%s: хук %s не підключений" % (event, fname))
                continue
            broken = []
            for c in mine:
                for tok in c.split():
                    if tok.endswith((".sh", ".py")) and not Path(tok).expanduser().exists():
                        broken.append(tok)
            if broken:
                out.append("BAD|%s: хук веде на неіснуючий шлях %s → виправ ~/.claude/settings.json на %s"
                           % (event, broken[0], kit / "scripts" / "hooks" / fname))
            else:
                out.append("OK|%s: %s підключений і файл на місці" % (event, fname))
print("\n".join(out))
PY
)

# ── 7. Чи не приїхало чуже ────────────────────────────────────────────
head_ "7. Чужі шляхи в тому, що відвантажується"
# 🔴 Копія кіта не має тягнути шляхи домашньої теки автора. Перевіряємо ФАКТ.
# 🔴 Коментарі НЕ рахуються: перевірка, що підсвічує пояснювальні рядки,
#    дорівнює відсутній — її перестають читати.
LEAKS="$("$PROBE_PY" - "$KIT" <<'PY' 2>/dev/null
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
bad = re.compile(r"/Volumes/|/Users/[A-Za-z]+")
skip_names = {"config.toml"}          # особистий конфіг не відвантажується
hits = []
for sub in ("scripts", "templates", "skills"):
    d = root / sub
    if not d.exists():
        continue
    for f in d.rglob("*"):
        if not f.is_file() or f.suffix not in {".py", ".sh", ".json", ".toml", ".md"}:
            continue
        if f.name in skip_names or "__pycache__" in f.parts or ".venv" in f.parts:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = line.lstrip()
            if s.startswith(("#", "//", "<!--", "*", '"_comment"')):
                continue
            if bad.search(line):
                hits.append("%s:%d: %s" % (f.relative_to(root), n, s[:70]))
print("\n".join(hits))
PY
)"
if [ -z "$LEAKS" ]; then
  ok "у коді нема ні чужих дисків, ні домашніх тек автора"
else
  bad "шляхи конкретної машини у коді:"
  echo "$LEAKS" | sed 's/^/       /'
fi

# ── 8. Оновлення, яке приїхало, але не застосоване ────────────────────
# 🔴 Секції може не бути взагалі: модуль живе у вищому тирі. Мовчання чесніше
#    за «✅ незастосованих оновлень немає» там, де ми цього просто не знаємо.
if [ -f "$KIT/scripts/update_actions.py" ]; then
head_ "8. Незастосовані оновлення"
# 🔴 Файли можуть приїхати git-ом, а фікс лишитись невиконаним: доставити
#    залежність, перечепити хук, переіндексувати. Доктор має це показувати —
#    інакше людина впевнена, що оновилась, а половина фіксу лежить.
#    Модуль живе у вищому тирі: його відсутність — не проблема, а тиша.
PENDING="$("$PROBE_PY" -c "
import sys; sys.path.insert(0, '$KIT/scripts')
try:
    import update_actions; print(update_actions.notice())
except BaseException:
    pass" 2>/dev/null)"
if [ -z "$PENDING" ]; then
  ok "незастосованих оновлень немає"
else
  bad "оновлення застосоване не повністю:"
  echo "$PENDING" | sed 's/^/       /'
fi
fi

# ── Лагодження ────────────────────────────────────────────────────────
if [ "$FIX" = 1 ] && [ -n "$NEEDS" ]; then
  head_ "Лагоджу"
  # setup.sh ідемпотентний і нічого не видаляє — ним і лагодимо оточення й теки.
  if has_need venv || has_need dirs || has_need config; then
    if bash "$KIT/scripts/setup.sh"; then
      fixed "прогнано scripts/setup.sh (оточення, теки, symlinks)"
    else
      bad "setup.sh завершився помилкою — далі руками"
    fi
  fi
  if has_need bge; then
    if command -v ollama >/dev/null 2>&1; then
      # ≈1.1 ГБ — кажемо ціну ДО завантаження, а не після.
      echo "  → тягну bge-m3 (≈1.1 ГБ, разово)…"
      ollama pull bge-m3 </dev/null && fixed "bge-m3 завантажено"
    else
      bad "ollama не в PATH — постав https://ollama.com або перемкнись на OpenRouter"
    fi
  fi
fi

# ── Підсумок ──────────────────────────────────────────────────────────
echo
if [ "$PROBLEMS" = 0 ]; then
  echo "✅ Проблем не знайдено."
else
  echo "🔴 Проблем: $PROBLEMS"
  [ "$FIX" = 0 ] && echo "   Спробувати полагодити автоматично:  bash doctor.sh --fix"
fi
[ "$FIXED" -gt 0 ] && echo "🔧 Полагоджено цим запуском: $FIXED (числа вище — ДО лагодження; прогони ще раз: bash doctor.sh)"
exit 0

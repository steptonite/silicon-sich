#!/bin/bash
# SessionStart hook — інжектить «де спинились» зі свіжого bridge.md + дисципліну +
# підказку librarian. Нуль зовнішніх викликів. Вивід — лише JSON у stdout.
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SB_KIT="$KIT" python3 - <<'PY'
import json, os, pathlib, sys

kit = pathlib.Path(os.environ["SB_KIT"])
sys.path.insert(0, str(kit / "scripts"))
try:
    from sb_config import CFG, P
except SystemExit:
    sys.exit(0)  # нема конфіга — хук мовчить

mem = P(CFG["vault"]["memory"])
bridge = mem / "bridge.md"
head = bridge.read_text(encoding="utf-8")[:1800] if bridge.exists() else "(bridge.md порожній)"
lib = kit / "scripts" / "librarian.py"
py = kit / ".venv" / "bin" / "python"
ctx = (
    "ВІДНОВЛЕННЯ СЕСІЇ (хук SessionStart). Гарячий стан із bridge.md (зріз):\n\n"
    + head +
    "\n\n🔴 ПАМ'ЯТЬ: (а) перед твердженнями про минуле — СПОЧАТКУ семантичний пошук, не вигадуй; "
    "(б) досягнення/рішення записуй у memory ОДРАЗУ, не в кінці сесії; (в) «записав» без "
    "показаного шляху файлу = брехня — завжди показуй доказ запису.\n"
    "— Семантичне пригадування (по СЕНСУ, не словах):\n"
    f"  {py} {lib} search \"тема\"\n"
    "— /compact: при стисненні модель САМА зберігає в bridge.md дослівно поточну задачу, "
    "шляхи файлів, рішення+ЧОМУ, наступний крок (PreCompact-хук цього не вміє)."
)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}, ensure_ascii=False))
PY

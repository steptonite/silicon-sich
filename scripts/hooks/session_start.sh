#!/bin/bash
# SessionStart hook — інжектить «де спинились» зі свіжого bridge.md + дисципліну +
# підказку librarian, а після /compact — ефемерний зріз стану (anti-compact safe).
# Нуль зовнішніх викликів. Вивід — лише JSON у stdout.
# ІНВАРІАНТ: хук ніколи не валить сесію — уся логіка чекпоінта в try/except.
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SB_KIT="$KIT" python3 - <<'PY'
import json, os, pathlib, sys, time

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

# Anti-compact safe: PreCompact-знімач лишає ефемерний зріз у diagnostic_dir.
diag = P(CFG.get("maintenance", {}).get("diagnostic_dir", "~/.config/second-brain/logs"))
CHECKPOINT = diag / "compact_checkpoint.md"
AUDIT = diag / "compact_snapshots.jsonl"
CHECKPOINT_BUDGET = 3500   # несуче (обов'язки + дослівні промти) має доїхати над лінією кліпу


def last_degraded() -> bool:
    """Чи був останній зріз degraded — читаємо МАШИННЕ поле з audit-JSONL, а не грепаємо
    текстовий літерал (крихко). Будь-яка біда → False (не панікуємо дарма)."""
    try:
        lines = AUDIT.read_text(encoding="utf-8", errors="replace").splitlines()
        for ln in reversed(lines):
            ln = ln.strip()
            if not ln:
                continue
            return bool(json.loads(ln).get("degraded"))
    except Exception:
        return False
    return False


def checkpoint_notice() -> str:
    """Якщо PreCompact щойно (≤2 год) лишив зріз — вкинути його, щоб переанкоруватись
    після стиснення незалежно від дисципліни моделі. Свіжість 2 год відсікає вчорашні
    зрізи на звичайному старті. Будь-яка біда → ''."""
    try:
        if not CHECKPOINT.exists():
            return ""
        if (time.time() - CHECKPOINT.stat().st_mtime) / 3600 > 2:
            return ""
        body = CHECKPOINT.read_text(encoding="utf-8", errors="replace").strip()
        if not body:
            return ""
        # Кліп ПОТИРНИЙ — ріжемо на межі `## `, щоб не рвати тир навпіл. Тири в зрізі
        # йдуть за пріоритетом (обов'язки → промти → L2 → bridge), тож несуче лишається.
        if len(body) > CHECKPOINT_BUDGET:
            cut = body.rfind("\n## ", 0, CHECKPOINT_BUDGET)
            if cut <= 0:
                cut = CHECKPOINT_BUDGET
            body = body[:cut].rstrip() + "\n… (повний зріз: diagnostic_dir/compact_checkpoint.md)"
        warn = ""
        if last_degraded():
            warn = ("⚠️ ЗРІЗ БУВ НЕПОВНИЙ (degraded) — дослівні промти не витяглись; "
                    "звір bridge.md вручну, не покладайся лише на цей блок.\n\n")
        return "\n\n" + warn + body + "\n"
    except Exception:
        return ""


try:
    safe = checkpoint_notice()
except Exception:
    safe = ""

# Незакрите рішення користувача (локально чи за гроші) — першим рядком, поки не вирішено.
# 🔴 22.08.2026: у першої платної установки це питання не поставили на установці, і воно просто зникло.
try:
    import embed_contract
    open_decision = embed_contract.notice()
except Exception:
    open_decision = ""

# Оновлення, яке приїхало, але не застосоване — теж борг, і теж має заважати,
# поки не закритий. Файл живе у вищому тирі ⇒ відсутність його НЕ помилка.
try:
    import update_actions
    pending = update_actions.notice()
except (Exception, SystemExit):
    pending = ""

ctx = (
    (pending + "\n\n" if pending else "")
    + (open_decision + "\n\n" if open_decision else "")
    + "ВІДНОВЛЕННЯ СЕСІЇ (хук SessionStart). Гарячий стан із bridge.md (зріз):\n\n"
    + safe
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

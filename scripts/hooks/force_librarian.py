#!/usr/bin/env python3
"""force_librarian.py — PostToolUse-хук: порожній пошук ≠ «файлу немає».

Навіщо це існує (22.08.2026):
дисципліна «спершу шукай у базі» весь час жила текстом — в AGENTS.md, у CLAUDE.md,
у голосових нагадуваннях. Текст агент читає й забуває. Перша платна установка це
показала дослівно: власник кита цілий день голосом просив агента користуватись
бібліотекою й записувати ноти — і щоразу мусив ловити його вручну.
Правило, яке треба нагадувати, — це не правило, а прохання.

Тому механіка замість прохання: щойно пошуковий виклик повернув порожньо — хук
сам вкидає вимогу зробити семантичний пошук. Пропустити не можна: текст приходить
у контекст без участі моделі.

Клас збою, який ловимо: пошук по імені файлу нічого не знайшов → модель робить
висновок «цього не існує» → вигадує вміст з голови. Насправді файл лежить під
іншою назвою, в іншій теці, іншою мовою — саме те, для чого існує пошук по змісту.

Реєстрація:
  Claude Code — ~/.claude/settings.json → hooks.PostToolUse, matcher "Bash|Grep|Glob"
  Codex       — ~/.codex/hooks.json     → PostToolUse
Обидва харнеси читають payload зі stdin і забирають stderr у контекст при rc=2.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

# Шляхи кита беремо ВІД СЕБЕ, не з машини автора: хук лежить у scripts/hooks/,
# отже корінь на два рівні вище. Це та сама помилка, що вбила панель KobzarAI
# у чужій машині, — жорсткий шлях автора у дефолті.
KIT = Path(__file__).resolve().parent.parent.parent
LIB = KIT / "scripts" / "librarian.py"
PY = KIT / ".venv" / "bin" / "python"
PY_CALL = f"{PY} {LIB}" if PY.exists() else f"python3 {LIB}"

# команди, які вважаємо ПОЛЮВАННЯМ на артефакт.
# Голого `ls` тут навмисно немає: перелік теки — побутова дія, і саме він давав
# хибні спрацювання на порожніх теках.
SEARCH = re.compile(r"\b(find|glob|grep|rg|fd|locate)\b")
LOOKING_FOR = re.compile(r"(-name|-iname|-path|--include|\*\.|\.md\b|prompt|skill|memory)")
# рахунок/тест — порожньо тут це валідна ВІДПОВІДЬ, а не провал пошуку
COUNTING = re.compile(r"\bgrep\b[^|]*\s-\w*[cqL]|\bwc\b|\btest\b|\[\[?\s-[ef]\b")
TOOL_SEARCH = {"Grep", "Glob"}
EMPTY_MARKS = ("no matches found", "no files found", "found 0 ")

STATE = Path(os.environ.get(
    "SB_FORCE_LIBRARIAN_STATE",
    "~/.config/second-brain/logs/force-librarian.state")).expanduser()
QUIET_SEC = 600   # у розвідці порожній пошук — норма; повна лекція щоразу це податок

SHORT = ("🔴 Знову порожній пошук (хук force_librarian). Те саме правило: порожньо ≠ немає. "
         "Другий захід — пошук по змісту іншим формулюванням, і лише потім вердикт.")

HINT = f"""🔴 ПОРОЖНІЙ ПОШУК ≠ ФАЙЛУ НЕМАЄ (хук force_librarian).

Твій пошуковий виклик повернув порожньо. Це означає «я шукав погано», а НЕ «цього не існує».
Файл може лежати під іншою назвою, в іншій теці або іншою мовою — саме для цього
в киті є пошук по ЗМІСТУ, а не по імені.

🔴 ЗАБОРОНЕНО до наступного кроку: вигадувати вміст, писати «не знайшов»,
робити саморобну заміну артефакту, який у базі вже може існувати.

ОБОВ'ЯЗКОВИЙ наступний хід:
  {PY_CALL} search "що тобі треба"

І не один раз: 2-3 різні формулювання (+ --source, якщо знаєш шар).
Тільки після цього маєш право сказати «немає»."""


def extract_command(tool: str, tin: dict) -> str | None:
    """Що саме шукали. None = цей виклик нас не стосується."""
    if tool in TOOL_SEARCH:
        # Grep/Glob — пошук за визначенням, гейт по команді не потрібен.
        # Це головна діра першої версії: харнес велить брати саме ці інструменти
        # замість shell, тобто хук стеріг рівно той шлях, яким модель НЕ ходить.
        return str(tin.get("pattern", ""))
    if tool != "Bash":
        return None
    cmd = tin.get("command", "") or ""
    if not SEARCH.search(cmd) or not LOOKING_FOR.search(cmd):
        return None
    if COUNTING.search(cmd):
        return None
    if "librarian" in cmd:      # пошук по змісту вже в цій же команді — не заважаємо
        return None
    return cmd


def is_empty(resp) -> bool:
    if isinstance(resp, dict):
        out = (resp.get("stdout") or "") + (resp.get("stderr") or "")
    else:
        out = str(resp or "")
    stripped = out.strip()
    low = stripped.lower()
    return (not stripped
            or any(m in low for m in EMPTY_MARKS)
            or stripped.endswith("No such file or directory"))


def recently_warned() -> bool:
    now = time.time()
    fresh = False
    try:
        fresh = now - float(STATE.read_text().strip()) < QUIET_SEC
    except (OSError, ValueError):
        pass
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(str(now))
    except OSError:
        pass
    return fresh


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0

    tool = payload.get("tool_name") or payload.get("tool") or ""
    tin = payload.get("tool_input") or {}
    if not isinstance(tin, dict):
        return 0

    if extract_command(str(tool), tin) is None:
        return 0
    if not is_empty(payload.get("tool_response")):
        return 0

    print(SHORT if recently_warned() else HINT, file=sys.stderr)
    return 2   # блокуючий код: текст іде в контекст як зауваження


if __name__ == "__main__":
    sys.exit(main())

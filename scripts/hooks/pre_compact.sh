#!/bin/bash
# PreCompact hook — ПОБІЧНИЙ ЕФЕКТ, без stdout.
#  embed-save: ФОНОВА інкрементна індексація поточних сесій у librarian-індекс,
#  щоб стиснення контексту не з'їдало пам'ять — усе вже лежить в індексі.
#  Відв'язано (&), щоб не блокувати стиснення.
#
# ВАЖЛИВО: PreCompact у Claude Code НЕ приймає hookSpecificOutput.additionalContext —
# stdout має бути ПОРОЖНІЙ, інакше "validation failed". Наказ-про-збереження стану
# живе в SessionStart-хуку + в CLAUDE.md-дисципліні (/compact-ритуал моделі).
#
# 22.07.2026 — ЛОК ВІД НАШАРУВАННЯ. Довга сесія дає багато стиснень підряд, і
# кожне запускало ще один повний скан транскриптів. Прогони накладались один на
# одного, паралельно молотили embed-модель і перегрівали машину.
# Атомарний mkdir пропускає стиснення, якщо індекс уже біжить. Замок, старший за
# STALE_MIN, вважається осиротілим після падіння і знімається.
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCK="${TMPDIR:-/tmp}/sbkit-index.lock"
STALE_MIN=30

if [ -d "$LOCK" ]; then
  if [ -z "$(find "$LOCK" -maxdepth 0 -mmin +$STALE_MIN 2>/dev/null)" ]; then
    exit 0                              # індексація вже біжить — пропускаємо
  fi
  rmdir "$LOCK" 2>/dev/null || true     # осиротілий замок
fi
mkdir "$LOCK" 2>/dev/null || exit 0     # програли гонку — теж пропускаємо

(
  "$KIT/.venv/bin/python" "$KIT/scripts/librarian.py" index --source transcripts >/dev/null 2>&1
  rmdir "$LOCK" 2>/dev/null
) >/dev/null 2>&1 &
exit 0

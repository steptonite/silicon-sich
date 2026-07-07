#!/bin/bash
# PreCompact hook — ПОБІЧНИЙ ЕФЕКТ, без stdout.
#  embed-save: ФОНОВА інкрементна індексація поточних сесій у librarian-індекс,
#  щоб стиснення контексту не з'їдало пам'ять — усе вже лежить в індексі.
#  Відв'язано (&), щоб не блокувати стиснення.
#
# ВАЖЛИВО: PreCompact у Claude Code НЕ приймає hookSpecificOutput.additionalContext —
# stdout має бути ПОРОЖНІЙ, інакше "validation failed". Наказ-про-збереження стану
# живе в SessionStart-хуку + в CLAUDE.md-дисципліні (/compact-ритуал моделі).
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
( "$KIT/.venv/bin/python" "$KIT/scripts/librarian.py" index --source transcripts >/dev/null 2>&1 & ) >/dev/null 2>&1
exit 0

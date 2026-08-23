#!/usr/bin/env bash
# Одна команда від нуля до працюючої бази.
#
#   bash install.sh                 # спитає тир
#   bash install.sh --tier v2       # без питань
#   bash install.sh --tier v2 --root ~/SecondBrain
#
# Безпечно запускати повторно і поверх уже наявної бази: перед будь-якою
# зміною робиться бекап, дані не перезаписуються.
set -euo pipefail

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIER=""; ROOT="$HOME/SecondBrain"; AGENT="both"

while [ $# -gt 0 ]; do
  case "$1" in
    --tier)  TIER="$2"; shift 2 ;;
    --root)  ROOT="$2"; shift 2 ;;
    --agent) AGENT="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Невідомий аргумент: $1" >&2; exit 2 ;;
  esac
done

echo "── Second Brain Kit ──"

# 1. Python. Причина перевірки: tomllib зʼявився у 3.11, а sqlite-vec потребує
#    збірки з увімкненими extensions — обидва провали інакше вилазять пізно й глухо.
#    🔴 22.08.2026: `command -v python3` на стоковій macOS віддає системний 3.9.6 —
#    інсталятор падав «постав новіший», хоча придатний Python уже стояв поруч
#    (brew, python.org, pyenv). Тому шукаємо ПРИДАТНИЙ, а не перший-ліпший.
py_ok() { [ -x "$1" ] && "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; }

PY_BIN=""
BREW_PREFIX="$(brew --prefix 2>/dev/null || echo /opt/homebrew)"
for CAND in \
  "$BREW_PREFIX/opt/python@3.12/bin/python3.12" \
  "$BREW_PREFIX/opt/python@3.13/bin/python3.13" \
  "$BREW_PREFIX/opt/python@3.11/bin/python3.11" \
  "$BREW_PREFIX/bin/python3" \
  "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3" \
  "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" \
  "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" \
  "$(command -v python3.13 || true)" \
  "$(command -v python3.12 || true)" \
  "$(command -v python3.11 || true)" \
  "$(command -v python3 || true)"
do
  if py_ok "$CAND"; then PY_BIN="$CAND"; break; fi
done

if [ -z "$PY_BIN" ]; then
  FOUND="$(command -v python3 || true)"
  if [ -n "$FOUND" ]; then
    echo "🔴 Знайдений python3 — це $("$FOUND" -V 2>&1), а треба 3.11+."
    echo "   Найпростіше:  brew install python@3.12   (або з python.org)"
  else
    echo "🔴 Немає python3. Постав Python 3.11+ з python.org і запусти знову."
  fi
  exit 1
fi
echo "→ Python: $PY_BIN ($("$PY_BIN" -V 2>&1))"

# 2. Тир. Питаємо тільки якщо не задано аргументом.
if [ -z "$TIER" ]; then
  echo
  "$PY_BIN" "$KIT/sbkit.py" tiers --root "$ROOT" || true
  echo
  CHOICES="$("$PY_BIN" "$KIT/sbkit.py" tiers --available)"
  DEFAULT_TIER="$("$PY_BIN" "$KIT/sbkit.py" tiers --default)"
  read -r -p "Який тир ставимо? [$CHOICES] (Enter = $DEFAULT_TIER) " TIER
  TIER="${TIER:-$DEFAULT_TIER}"
fi

# 3. Оточення. venv у корені кита — щоб хуки знаходили його від свого шляху.
if [ ! -x "$KIT/.venv/bin/python" ]; then
  echo "── створюю оточення…"
  bash "$KIT/scripts/setup.sh"
else
  echo "── оточення вже є, пропускаю"
fi

# 4. Конфіг. НІКОЛИ не перезаписуємо існуючий — там уже можуть бути чужі шляхи.
if [ ! -f "$KIT/scripts/config.toml" ]; then
  cp "$KIT/scripts/config.example.toml" "$KIT/scripts/config.toml"
  echo "── конфіг створено: $KIT/scripts/config.toml"
else
  echo "── конфіг на місці, не чіпаю"
fi

# 4b. Договір про ембединги. 🔴 22.08.2026: без цього кроку питання «локально чи
#     за гроші» просто розчинялось — людина ставила кит, не піднявши Ollama, далі
#     агент рапортував «$0», а гроші списувались. Питаємо ОДИН раз; «пізніше» —
#     теж валідна відповідь, але вона стає боргом, який хуки нагадують на старті.
DECIDED="$("$PY_BIN" "$KIT/scripts/embed_contract.py" status | grep -c '"status": "decided"' || true)"
if [ "$DECIDED" = "0" ]; then
  if [ -t 0 ]; then
    "$PY_BIN" "$KIT/scripts/embed_contract.py" ask
  else
    echo "── неінтерактивна установка: питання про ембединги НЕ пропущено, а відкладено."
    echo "   Закрий його вручну:  $PY_BIN $KIT/scripts/embed_contract.py ask"
  fi
else
  echo "── ембединги: рішення вже ухвалено, не перепитую"
fi

# 5. Установка. Ідемпотентна, бекап-перша, підхоплює наявну базу.
echo "── ставлю $TIER у $ROOT"
"$PY_BIN" "$KIT/sbkit.py" install --tier "$TIER" --root "$ROOT" --agent "$AGENT"

# 6. Перевірка.
echo
echo "── перевірка оточення:"
"$PY_BIN" "$KIT/sbkit.py" doctor --root "$ROOT" || true

# 7. Одна доречна пропозиція супутника — якщо для неї є привід.
if [ -f "$KIT/scripts/companions.py" ]; then
  echo
  "$PY_BIN" "$KIT/scripts/companions.py" || true
fi

cat <<EOF

✅ Готово. Далі:
   1. Відредагуй $KIT/scripts/config.toml — там шляхи до твоїх архівів.
   2. Поклади експорти чатів і сконвертуй: docs/01-export.md, docs/02-convert.md
   3. Збери індекс:  $KIT/.venv/bin/python $KIT/scripts/librarian.py index
   4. Перевір пошук: $KIT/.venv/bin/python $KIT/scripts/librarian.py search "будь-яка тема"

   Куди йшли ембединги (і чи платив):  python3 $KIT/scripts/embed_journal.py
   Що стоїть зараз:  python3 $KIT/sbkit.py tiers --root $ROOT
   Підняти тир:      python3 $KIT/sbkit.py upgrade --to <тир> --root $ROOT
EOF

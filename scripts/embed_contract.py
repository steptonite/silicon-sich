#!/usr/bin/env python3
"""Договір про ембединги: рішення ухвалюється ОДИН раз на установці — і не губиться.

Чому це окремий файл, а не рядок у config.toml (22.08.2026):

Перша людина з платною копією поставила кит, не піднявши Ollama і не налаштувавши
OpenRouter одразу. Далі все поїхало наосліп: агент казав «локально, $0», гроші
списувались, а спитати було ніде — конфіг мовчазний, у ньому просто стоїть дефолт, і не видно, чи це
СВІДОМИЙ вибір людини, чи «так вийшло». Різниця між «людина дозволила» і «ніхто
не питав» у конфізі не виражається взагалі.

Тому рішення винесено в окремий стан із трьома значеннями, а не двома:
  decided       — людина обрала, працюємо мовчки;
  deferred      — людина сказала «пізніше»: це НЕ дефолт, це борг. Хуки нагадують
                  на кожному старті сесії, поки не закриють. Забути не можна;
  (нічого)      — кит стоїть, а питання не ставили: така сама дірка, як deferred.

🔴 Дефолт при невирішеному — найдорожчий за часом, найдешевший за грошима:
локально й зупинитись. Мовчки платити не можна НІКОЛИ; мовчки не працювати — можна.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

STATE = Path(os.environ.get(
    "SB_EMBED_DECISION", "~/.config/second-brain/embed-decision.json")).expanduser()

# (ключ, підпис, openrouter_enabled, openrouter_fallback)
CHOICES = {
    "1": ("local", "Тільки локально (Ollama) — $0, тексти не покидають Mac", False, False),
    "2": ("cloud", "Тільки через OpenRouter — платно, тексти йдуть на чужий сервер", True, True),
    "3": ("auto",  "Локально, а якщо Ollama лежить — автоматично OpenRouter (платно)", True, True),
    "4": ("ask",   "Локально; якщо Ollama лежить — ЗУПИНИТИСЬ і спитати мене", True, False),
}

QUESTION = """
──────────────────────────────────────────────────────────────────────
Одне питання, яке треба закрити зараз, бо потім воно коштує грошей.

Пошук по твоїй базі працює так: текст перетворюється на числа («ембединг»).
Це робить або програма на твоєму Mac, або чужий сервер за гроші.

  1) Тільки локально (Ollama). $0. Твої тексти нікуди не йдуть.
     Треба поставити Ollama + модель bge-m3 (~1.1 ГБ).
  2) Тільки OpenRouter. Платно, тексти йдуть у мережу. Ставити нічого не треба.
  3) Локально, а якщо Ollama не запущена — САМО піде в OpenRouter (платно).
     Зручно, але списання ти помітиш постфактум.
  4) Локально, а якщо Ollama не запущена — зупинитись і спитати. (за замовчуванням)

  0) Вирішу пізніше — тоді агент нагадуватиме на КОЖНОМУ старті, поки не закриєш.
──────────────────────────────────────────────────────────────────────"""


def load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save(data: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_open() -> bool:
    """Питання вважається відкритим і поки людина не обрала, і поки її не питали."""
    return load().get("status") != "decided"


def notice() -> str:
    """Текст, який хуки вкидають агенту, поки борг не закрито. Порожньо = все гаразд."""
    st = load()
    if st.get("status") == "decided":
        return ""
    who = "відкладене рішення" if st.get("status") == "deferred" else "питання ніколи не ставили"
    return (
        f"🔴 НЕЗАКРИТЕ РІШЕННЯ КОРИСТУВАЧА ({who}): не обрано, як робити ембединги — "
        "локально (Ollama, $0) чи через OpenRouter (платно, тексти йдуть у мережу). "
        "Поки не обрано, кит працює найобережніше: локально, і зупиняється замість того, "
        "щоб мовчки платити. 🔴 ТИ МУСИШ підняти це питання перед користувачем цієї сесії "
        "простою мовою (без слів «ембединг», «бекенд», «фолбек») і закрити його командою "
        "`python3 scripts/embed_contract.py ask`. Не відкладай удруге мовчки — "
        "якщо людина знову каже «пізніше», так і запиши, але СКАЖИ, що це лишається боргом."
    )


def apply_to_config(key: str) -> str:
    """Прописати вибір у config.toml. Повертає рядок звіту (або причину, чому не вийшло)."""
    _, _, enabled, fallback = next(v for v in CHOICES.values() if v[0] == key)
    cfg = Path(os.environ.get("SB_CONFIG", "")) if os.environ.get("SB_CONFIG") else \
        Path(__file__).resolve().parent / "config.toml"
    if not cfg.is_file():
        return f"⚠️ config.toml не знайдено ({cfg}) — вибір збережено, але у файл не вписано."
    text = cfg.read_text(encoding="utf-8")
    for name, value in (("openrouter_enabled", enabled), ("openrouter_fallback", fallback)):
        new_line = f"{name} = {'true' if value else 'false'}"
        out, hit = [], False
        for line in text.splitlines():
            if line.strip().startswith(name) and "=" in line and not hit:
                out.append(new_line)
                hit = True
            else:
                out.append(line)
        if not hit:
            return f"⚠️ у config.toml немає рядка {name} — вписати не вийшло."
        text = "\n".join(out) + ("\n" if text.endswith("\n") else "")
    cfg.write_text(text, encoding="utf-8")
    return f"✅ вписано в {cfg}"


def ask(stream=sys.stdin) -> int:
    print(QUESTION)
    try:
        raw = input("Твій вибір [1/2/3/4/0], Enter = 4: ").strip()
    except (EOFError, KeyboardInterrupt):
        raw = "0"
    if raw == "0":
        st = load()
        save({"status": "deferred",
              "deferrals": int(st.get("deferrals", 0)) + 1,
              "note": "людина сказала «пізніше»; агент нагадує на кожному старті"})
        print("\n⏸  Записано як ВІДКЛАДЕНЕ. Це не «за замовчуванням» — це борг:\n"
              "   агент нагадає про нього на початку кожної сесії, поки не закриєш.\n"
              "   Поки що кит працює локально і НЕ платить мовчки.")
        return 0
    key, label, _, _ = CHOICES.get(raw or "4", CHOICES["4"])
    save({"status": "decided", "choice": key, "label": label})
    print(f"\n✅ Обрано: {label}")
    print("   " + apply_to_config(key))
    if key in ("local", "auto", "ask"):
        print("   Перевірити, що Ollama жива:  ollama serve   (модель: ollama pull bge-m3)")
    if key in ("cloud", "auto"):
        print("   🔴 Це платний режим. Що реально витрачалось — "
              "`python3 scripts/embed_journal.py`")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "ask":
        sys.exit(ask())
    if cmd == "notice":
        text = notice()
        print(text) if text else None
        sys.exit(0)
    st = load()
    print(json.dumps(st or {"status": "never-asked"}, ensure_ascii=False, indent=2))

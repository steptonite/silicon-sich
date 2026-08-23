#!/usr/bin/env python3
"""Журнал ембедингів: ЩО реально відпрацювало, а не що агент сказав.

Причина існування (Льоша, 22.08.2026, після першої платної установки):
агент рапортував «працює локально, $0», а насправді йшов фолбек на OpenRouter —
і мовчав. Попередження librarian друкувалось у stderr, але Codex його не
переказує, тож для людини різниці не було видно НІЯК.

Тому рішення не «друкувати гучніше», а «лишати слід»: кожен реальний виклик
ембедера дописує рядок сюди. Після цього твердження «все локально» перевіряється
однією командою й перестає бути питанням довіри:

    python3 scripts/librarian.py usage

🔴 Журнал НЕ містить самих текстів — тільки рушій, кількість і обсяг у символах.
Це навмисно: файл має бути безпечним, щоб його можна було показати комусь
у скріншоті, не злив нічого зі своєї бази.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

JOURNAL = Path(os.environ.get(
    "SB_EMBED_JOURNAL", "~/.config/second-brain/embed-usage.jsonl")).expanduser()
MAX_LINES = 2000       # журнал не має рости вічно; тримаємо хвіст


def record(engine: str, n_texts: int, n_chars: int, *, command: str = "") -> None:
    """Дописати один факт. Будь-яка помилка тут НЕ має ламати пошук."""
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "engine": engine,
            "texts": int(n_texts),
            "chars": int(n_chars),
            "cmd": command[:40],
            "paid": engine != "ollama",
        }, ensure_ascii=False)
        with JOURNAL.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        _trim()
    except OSError:
        pass


def _trim() -> None:
    try:
        if JOURNAL.stat().st_size < 400_000:
            return
        lines = JOURNAL.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_LINES:
            JOURNAL.write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def read(limit: int = 0) -> list[dict]:
    try:
        lines = JOURNAL.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for raw in lines[-limit:] if limit else lines:
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def summary(limit: int = 0) -> str:
    rows = read(limit)
    if not rows:
        return ("Журнал ембедингів порожній — жодного виклику ще не було "
                f"(або файл прибрано): {JOURNAL}")
    agg: dict[str, dict[str, int]] = {}
    for r in rows:
        a = agg.setdefault(r.get("engine", "?"), {"calls": 0, "texts": 0, "chars": 0})
        a["calls"] += 1
        a["texts"] += int(r.get("texts", 0))
        a["chars"] += int(r.get("chars", 0))
    lines = [f"Журнал ембедингів: {JOURNAL}", f"Записів: {len(rows)}"
             + (f" (останні {limit})" if limit else " (усі)"), ""]
    for engine, a in sorted(agg.items(), key=lambda kv: -kv[1]["calls"]):
        money = "$0, локально" if engine == "ollama" else "🔴 ПЛАТНО, у мережу"
        lines.append(f"  {engine:<12} {a['calls']:>5} викликів · "
                     f"{a['texts']:>7} текстів · {a['chars']:>9} символів · {money}")
    paid = [r for r in rows if r.get("paid")]
    lines.append("")
    if paid:
        first, last = paid[0]["ts"], paid[-1]["ts"]
        lines.append(f"🔴 Платних викликів: {len(paid)} (з {first} по {last}). "
                     "Якщо ти цього не дозволяв — embed.openrouter_fallback має бути false.")
    else:
        lines.append("✅ Платних викликів не було жодного — усе пройшло локально.")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    print(summary(int(sys.argv[1]) if len(sys.argv) > 1 else 0))

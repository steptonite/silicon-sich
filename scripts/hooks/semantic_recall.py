#!/usr/bin/env python3
"""UserPromptSubmit: hybrid recall with a stable JSON contract and anti-anchoring."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
PY = os.environ.get("LIBRARIAN_PY", str(KIT / ".venv" / "bin" / "python"))
LIB = os.environ.get("LIBRARIAN_CLI", str(KIT / "scripts" / "librarian.py"))
LOG_PATH = Path(os.environ.get(
    "SEMANTIC_RECALL_LOG", Path.home() / ".config/second-brain/logs/semantic_recall.log"
)).expanduser()

MAX_HITS = 3
MAX_SNIPPET = 300
STRONG_SNIPPET = 600

# 22.08.2026 — знайдено на живій установці користувача: у поточний промпт приїхали
# персонажі зовсім іншого проєкту. Причина механічна: хук інжектив ЛЮБИЙ збіг із
# топ-3, без стелі відстані. Ярлик «фон, не якір» шуму не спиняє — слабші моделі
# анкеряться на текст, а не на попередження.
#   dist <= STRONG_DIST            -> сильний: «прочитай першоджерело»
#   ranked (vector_rank <= RANK) і dist <= RANKED_DIST -> теж сильний
#   STRONG_DIST < dist <= DROP_DIST -> слабкий, явно як фон
#   dist > DROP_DIST                -> ВИКИДАЄМО, у контекст не потрапляє
STRONG_DIST, RANKED_DIST, STRONG_RANK, DROP_DIST = 0.85, 0.92, 3, 1.00

# Піднімати до «сильного» можна ЛИШЕ куроване. Сирі чати/транскрипти librarian
# СВІДОМО тримає у weak — вони не верифіковані й не мають анкерити модель.
CURATED = {"memory", "vault", "tasks", "knowledge", "external"}


def is_strong(hit: dict) -> bool:
    """Сильний ДЛЯ ЦІЛЕЙ ПРИГАДУВАННЯ: або топ-ранг із притомною відстанню, або
    відстань, яка говорить сама за себе. Тільки на курованих джерелах."""
    if hit.get("confidence") == "strong":
        return True
    dist = hit.get("vector_distance")
    if dist is None or hit.get("source") not in CURATED:
        return False
    if hit.get("status") in {"raw", "superseded"} or hit.get("warnings"):
        return False
    rank = hit.get("vector_rank")
    ranked_ok = rank is not None and rank <= STRONG_RANK and dist <= RANKED_DIST
    return ranked_ok or dist <= STRONG_DIST


def within_reach(hit: dict) -> bool:
    """Далекий збіг — це не слабкий доказ, це шум. Відстань без числа лишаємо
    (fts-влучання приходить без вектора) — її ріже сам librarian."""
    dist = hit.get("vector_distance")
    return not isinstance(dist, (int, float)) or dist <= DROP_DIST


def report_failure(reason: str, data: dict) -> None:
    """Do not break the session, but never make recall failure invisible."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as log:
            log.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {reason[:500]}\n")
        session = str(data.get("session_id") or data.get("sessionId") or "unknown")
        session = "".join(ch for ch in session if ch.isalnum() or ch in "-_")[:80]
        marker = LOG_PATH.parent / f".semantic-recall-warned-{session}"
        if marker.exists():
            return
        marker.touch()
    except OSError:
        pass
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                "⚠️ semantic recall unavailable: автоматичний пошук не відпрацював. "
                "Найчастіша причина — не піднятий Ollama (`ollama serve`, або кнопка "
                "«Запустити» в KobzarAI). Не роби тверджень про минуле з пам'яті; "
                "запусти librarian вручну або скажи про це користувачу."
            ),
        }
    }, ensure_ascii=False))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    prompt = (data.get("prompt") or "").strip()
    if len(prompt) < 12 or prompt.startswith("/"):
        return
    try:
        proc = subprocess.run(
            [PY, LIB, "search", prompt[:500], "-k", str(MAX_HITS + 2),
             "--backend", "ollama", "--retrieval", "hybrid", "--format", "json"],
            capture_output=True, text=True, timeout=25,
        )
    except Exception as exc:
        report_failure(f"subprocess: {type(exc).__name__}: {exc}", data)
        return
    if proc.returncode != 0 or not proc.stdout:
        report_failure(f"librarian exit={proc.returncode}: {proc.stderr.strip()}", data)
        return
    try:
        hits = json.loads(proc.stdout).get("results", [])[:MAX_HITS]
    except (json.JSONDecodeError, AttributeError) as exc:
        report_failure(f"invalid JSON: {exc}", data)
        return
    if not hits:
        return

    hits = [hit for hit in hits if within_reach(hit)]
    if not hits:
        return
    strong = [hit for hit in hits if is_strong(hit)]
    weak = [hit for hit in hits if not is_strong(hit)]

    def hit_line(hit: dict, limit: int) -> str:
        dist = hit.get("vector_distance")
        dist_label = f"{dist:.2f}" if isinstance(dist, (int, float)) else "n/a"
        body = " ".join(str(hit.get("snippet", "")).split())[:limit]
        return (f"• [{hit.get('source')}] {hit.get('ref')} "
                f"({hit.get('retrieval_reason')}, dist {dist_label}): {body}")

    lines = [
        "🧠 АВТО-ПРИГАДУВАННЯ (hybrid librarian, локально): це retrieval-кандидати, "
        "не готова відповідь. Сирі джерела не верифіковані й можуть бути застарілі."
    ]
    if strong:
        lines.append("🎯 СИЛЬНІ збіги — прочитай першоджерело ПЕРЕД відповіддю:")
        lines.extend(hit_line(hit, STRONG_SNIPPET) for hit in strong)
    if weak:
        lines.append(
            "⚠️ Слабкі збіги — ФОН, НЕ якір. Зроби 2–3 власні переформулювання "
            "та keyword/source-фолбек, якщо тема не збігається:"
        )
        lines.extend(hit_line(hit, MAX_SNIPPET) for hit in weak)
    if len(hits) > 1 and len({hit.get("ref") for hit in hits}) == 1:
        lines.append("⚠️ Всі збіги з одного файла — не звужуй пошук до нього.")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n".join(lines),
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

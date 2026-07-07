#!/usr/bin/env python3
"""PostToolUse-хук (Write|Edit): лінт канону memory-vault у момент запису.

Мета: моделі створюють ноти-«острови» — без uplink на хаб, без паралелей. Канон
модель у момент запису не читає, тому дисципліну переносимо в харнес: порушила
канон → хук одразу повертає моделі чек-ліст що дофіксити + семантичні кандидати
на wikilinks (librarian).

Не блокує запис (файл уже на диску) — лише дає моделі фідбек через decision:block,
щоб вона дописала лінки НЕГАЙНО, в тій самій сесії. Будь-яка помилка → мовчки exit 0.
Вимкнути: прибрати блок PostToolUse memory_lint у ~/.claude/settings.json.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
PY = str(KIT / ".venv" / "bin" / "python")
LIB = str(KIT / "scripts" / "librarian.py")
sys.path.insert(0, str(KIT / "scripts"))
try:
    from sb_config import CFG, P
    MEM = P(CFG["vault"]["memory"])
except SystemExit:
    sys.exit(0)  # нема конфіга — хук мовчить, сесію не ламає

# Службові файли — не ноти, канон на них не поширюється
SKIP = {"MEMORY.md", "bridge.md"}


def link_candidates(text: str) -> list[str]:
    """Топ-3 семантичні сусіди ноти з source=memory — кандидати на [[паралелі]]."""
    try:
        out = subprocess.run(
            [PY, LIB, "search", text[:400], "-k", "6", "--backend", "ollama",
             "--source", "memory"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return []
    names = []
    for m in re.finditer(r"── \[memory\] (\S+?)\.md #\d+\s+\(dist ([\d.]+)\)", out):
        nm, dist = m.group(1), float(m.group(2))
        if dist <= 1.0 and nm not in names and f"{nm}.md" not in SKIP:
            names.append(nm)
    return names[:3]


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    fp = (data.get("tool_input") or {}).get("file_path") or ""
    try:
        p = Path(fp).resolve()
        p.relative_to(MEM.resolve())
    except Exception:
        return  # запис не в memory-теку — не наша справа
    if p.name in SKIP or p.suffix != ".md" or not p.exists():
        return

    text = p.read_text(errors="ignore")
    problems = []
    if not text.startswith("---"):
        problems.append("нема frontmatter (--- name/description/metadata.type ---)")
    body = re.sub(r"^---.*?---", "", text, count=1, flags=re.S)
    links = set(re.findall(r"\[\[([^\]|#]+)", body))
    if not re.search(r"\[\[hub_\w+", text, re.I) and not p.name.startswith("hub_"):
        problems.append("нема uplink на хаб — додай `Uplink: [[hub_...]]` (обери свій хаб)")
    if len(links) < 2 and not p.name.startswith("hub_"):
        problems.append("менше 2 wikilinks — нота-острів; злінкуй паралелі до сусідніх нот")
    if not re.search(r"\d{2}\.\d{2}\.\d{4}", text):
        problems.append("нема жодної дати ДД.ММ.РРРР")
    idx_file = MEM / "MEMORY.md"
    idx = idx_file.read_text(errors="ignore") if idx_file.exists() else ""
    if f"({p.name})" not in idx:
        problems.append(f"нема рядка в MEMORY.md — додай `- [Назва]({p.name}) — гачок` у розділ хаба")
    if not problems:
        return

    cands = [c for c in link_candidates(body) if c != p.stem and c not in links]
    hint = ("\nСемантичні кандидати на [[паралелі]] (librarian): "
            + ", ".join(f"[[{c}]]" for c in cands)) if cands else ""
    reason = (
        f"📐 КАНОН VAULT (хук memory_lint): нота {p.name} записана, але порушує канон. "
        f"ДОФІКСИ ЗАРАЗ, не відкладай:\n"
        + "\n".join(f"  • {x}" for x in problems) + hint
        + "\nПісля фіксу нічого не відповідай хуку — просто відредагуй файл."
    )
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


if __name__ == "__main__":
    main()

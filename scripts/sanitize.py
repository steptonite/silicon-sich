#!/usr/bin/env python3
"""sanitize.py — механічний lint/audit memory-графа (детермінований, НЕ LLM).

Перевіряє інваріанти канону vault (див. templates/canon):
  • 0 битих wikilink (лінк резолвиться в memory або в крос-базі master-vault)
  • name: у frontmatter == імені файлу
  • кожна нота (крім хабів/службових) має uplink на hub_*
  • MEMORY.md не роздувся (індекс, не звалище)

РЕЖИМИ:
  --audit     перевірка інваріантів, exit 1 якщо є порушення (дефолт)
  --fix-names вирівняти `name:` == імені файлу (єдина безпечна авто-правка)

Філософія lint: ФЛАГУЄ проблеми, не переписує зміст мовчки. Семантичні правки
(зливання нот, переформулювання) — лише людина або модель за явним наказом.

  python sanitize.py --audit
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sb_config import CFG, P

MEM = P(CFG["vault"]["memory"])
ARCHIVES = [P(CFG["archives"][k]) for k in ("chatgpt", "gemini", "claude")]
# Службові файли — не ноти, канон на них не поширюється
SKIP = {"MEMORY.md", "bridge.md"}
MEMORY_MD_MAX_KB = 17

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(\|[^\]]+)?\]\]")


def frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[:end] if end != -1 else ""


def cross_base_targets() -> set[str]:
    """Basename-и всіх .md крос-баз (архівів) — валідні wikilink-цілі master-vault."""
    cross = set()
    for d in ARCHIVES:
        if d.exists():
            for f in d.rglob("*.md"):
                cross.add(f.name[:-3])
                try:
                    cross.add(str(f.relative_to(d.parent))[:-3])  # base/sub/name
                except ValueError:
                    pass
    return cross


def audit() -> bool:
    if not MEM.exists():
        print(f"AUDIT: memory-тека не існує: {MEM}")
        return False
    valid = {p.name for p in MEM.glob("*.md")}
    cross = cross_base_targets()
    broken, namebad, no_uplink = [], [], []
    for p in sorted(MEM.glob("*.md")):
        if p.name in SKIP:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        base = p.name[:-3]
        m = re.search(r"(?m)^name:\s*(.+)$", frontmatter(text))
        if m and m.group(1).strip() != base:
            namebad.append(f"{p.name}: name={m.group(1).strip()}")
        if not p.name.startswith("hub_") and not re.search(r"\[\[hub_\w+", text):
            no_uplink.append(p.name)
        for mm in WIKILINK_RE.finditer(text):
            t = mm.group(1).strip()
            if t == "MEMORY" or t + ".md" in valid or t in cross:
                continue
            broken.append(f"{p.name}: [[{t}]]")
    print("AUDIT:")
    print(f"  битих wikilink: {len(broken)}")
    for b in broken:
        print("   ", b)
    print(f"  name!=filename: {len(namebad)}")
    for n in namebad:
        print("   ", n)
    print(f"  без uplink на hub_*: {len(no_uplink)}")
    for n in no_uplink:
        print("   ", n)
    idx = MEM / "MEMORY.md"
    if idx.exists():
        kb = idx.stat().st_size / 1024
        print(f"  MEMORY.md: {kb:.1f} KB (<{MEMORY_MD_MAX_KB} ціль)")
    return not (broken or namebad or no_uplink)


def fix_names() -> int:
    n = 0
    for p in sorted(MEM.glob("*.md")):
        if p.name in SKIP:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        fm = frontmatter(text)
        if not fm:
            continue
        base = p.name[:-3]
        new_fm, cnt = re.subn(r"(?m)^name:.*$", f"name: {base}", fm, count=1)
        if cnt and new_fm != fm:
            p.write_text(new_fm + text[len(fm):], encoding="utf-8")
            print(f"  name-fix: {p.name}")
            n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", action="store_true", default=True)
    ap.add_argument("--fix-names", action="store_true")
    a = ap.parse_args()
    if a.fix_names:
        print(f"Виправлено name: у {fix_names()} файлах")
    ok = audit()
    sys.exit(0 if ok else 1)

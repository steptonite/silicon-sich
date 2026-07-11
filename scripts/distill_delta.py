#!/usr/bin/env python3
"""Детермінований preflight курованої ноти; нічого не переписує."""
import argparse, re
from pathlib import Path
ap=argparse.ArgumentParser(); ap.add_argument("path"); a=ap.parse_args(); bad=0
for p in sorted(Path(a.path).rglob("*.md")):
    t=p.read_text(errors="ignore"); issues=[]
    if not re.search(r"\b\d{2}\.\d{2}\.\d{4}\b",t): issues.append("немає абсолютної дати")
    if "[[" not in t: issues.append("немає wikilink-провенансу")
    if any(x in t.lower() for x in ("можливо","ймовірно","неперевірено")) and "⚠️" not in t: issues.append("невпевненість без ⚠️")
    if issues: bad+=1; print(f"FAIL {p}: "+"; ".join(issues))
    else: print(f"OK   {p}")
raise SystemExit(1 if bad else 0)

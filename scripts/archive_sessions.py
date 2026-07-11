#!/usr/bin/env python3
"""Конфігурований інкрементальний JSONL→MD адаптер локальних агентних сесій."""
import argparse, hashlib, json, re
from datetime import datetime
from pathlib import Path

def title(fp):
    try:
        for line in fp.open(errors="ignore"):
            o=json.loads(line); text=json.dumps(o,ensure_ascii=False)
            m=re.search(r'"content"\s*:\s*"([^"\\]{8,100})',text)
            if m: return m.group(1)
    except Exception: pass
    return "Agent session"
def slug(s): return re.sub(r"-+","-",re.sub(r"[^A-Za-zА-Яа-яІіЇїЄєҐґ0-9]+","_",s)).strip("_")[:55] or "Agent_session"
ap=argparse.ArgumentParser(); ap.add_argument("--source",required=True); ap.add_argument("--out",required=True); ap.add_argument("--label",required=True); a=ap.parse_args()
src=Path(a.source).expanduser(); out=Path(a.out).expanduser(); md=out/"md"; raw=out/"raw"; statef=out/"state.json"; md.mkdir(parents=True,exist_ok=True); raw.mkdir(parents=True,exist_ok=True)
state=json.loads(statef.read_text()) if statef.exists() else {}; changed=0
for fp in sorted(src.rglob("*.jsonl")) if src.exists() else []:
    key=str(fp); sig=f"{fp.stat().st_mtime_ns}:{fp.stat().st_size}"
    if state.get(key)==sig: continue
    short=hashlib.sha1(key.encode()).hexdigest()[:8]; day=datetime.fromtimestamp(fp.stat().st_mtime).strftime("%Y-%m-%d"); name=f"{day}_{slug(title(fp))}_{short}.md"
    (raw/f"{short}.jsonl").write_bytes(fp.read_bytes())
    (md/name).write_text(f"---\nsource: {a.label}\ncreated: {day}\nsource_file_id: {short}\n---\n\n# {title(fp)}\n\n> ⚠️ Сира локальна сесія; не куроване знання.\n",encoding="utf-8")
    state[key]=sig; changed+=1
statef.write_text(json.dumps(state,indent=2)); print(f"{a.label}: changed={changed}")

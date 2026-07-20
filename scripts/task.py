#!/usr/bin/env python3
"""Локальні Markdown-задачі: active → archive/YYYY-MM, без видалення історії."""
from __future__ import annotations
import argparse, re, subprocess, sys
from datetime import datetime
from pathlib import Path
from sb_config import CFG, P

ROOT = P(CFG["vault"].get("tasks", "~/SecondBrain/tasks")); ACTIVE = ROOT / "active"; ARCHIVE = ROOT / "archive"
DATE = "%d.%m.%Y"; DATETIME = "%d.%m.%Y %H:%M"

def now(): return datetime.now().strftime(DATETIME)
def slug(s): return re.sub(r"-+", "-", re.sub(r"[^a-zа-яіїєґ0-9]+", "-", s.lower())).strip("-")[:60] or "task"
def files(): return sorted(ACTIVE.glob("*.md")) + sorted(ARCHIVE.glob("*/*.md"))
def parse(p):
    text=p.read_text(encoding="utf-8"); m=re.match(r"---\n(.*?)\n---\n", text, re.S); d={}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k,v=line.split(":",1); d[k.strip()]=v.strip().strip('"')
    return d,text
def locate(tid):
    for p in files():
        if parse(p)[0].get("task_id")==tid: return p
    raise SystemExit(f"ERROR: task не знайдено: {tid}")
def write(p,d):
    body=(f"# {d['title']}\n\n## Context\n\n{d.get('context','')}\n\n## Completion condition\n\n{d.get('completion','')}\n")
    fm="\n".join(f'{k}: "{str(v).replace(chr(34), chr(39))}"' for k,v in d.items())
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+".tmp"); tmp.write_text(f"---\n{fm}\n---\n\n{body}",encoding="utf-8"); tmp.replace(p)
def reindex():
    lib=Path(__file__).with_name("librarian.py")
    kit_python=Path(__file__).resolve().parent.parent/".venv"/"bin"/"python"
    py=str(kit_python if kit_python.exists() else Path(sys.executable))
    p=subprocess.run([py,str(lib),"index","--source","tasks"],capture_output=True,text=True)
    if p.returncode:
        print("WARN: task збережено, але semantic index не оновлено; запусти setup.sh і index --source tasks",file=sys.stderr)
def add(a):
    stamp=datetime.now(); tid=f"task_{stamp:%Y%m%d_%H%M%S}"; d={"task_id":tid,"type":"task","title":a.title,"project":a.project,"status":"open","created":now(),"updated":now(),"due":a.due or "","remind_at":a.remind or "","source":a.source or "","author":a.author,"context":a.context or "","completion":a.completion or ""}
    p=ACTIVE/f"{stamp:%Y-%m-%d}_{slug(a.title)}_{tid}.md"; write(p,d); reindex(); print(f"{tid}\t{p}")
def listing(a):
    for p in sorted(ACTIVE.glob("*.md")):
        d,_=parse(p)
        if (not a.project or d.get("project")==a.project) and (not getattr(a,"before",None) or d.get("due") and datetime.strptime(d["due"],DATE)<=datetime.strptime(a.before,DATE)):
            print("\t".join([d.get("task_id",""),d.get("status",""),d.get("due",""),d.get("project",""),d.get("title","")]))
def show(a): print(locate(a.task_id).read_text(encoding="utf-8"))
def edit(a):
    p=locate(a.task_id); d,_=parse(p)
    for k in ("title","project","due","remind","context","completion"):
        v=getattr(a,k,None)
        if v is not None: d["remind_at" if k=="remind" else k]="" if v=="none" else v
    d["updated"]=now(); d["author"]=a.author; write(p,d); reindex(); print(p)
def move(a,done):
    p=locate(a.task_id); d,_=parse(p); d["status"]="done" if done else "open"; d["updated"]=now(); d["author"]=a.author
    if done: d["completed"]=now(); target=ARCHIVE/datetime.now().strftime("%Y-%m")/p.name
    else: d.pop("completed",None); target=ACTIVE/p.name
    write(target,d)
    if target!=p: p.unlink()
    reindex(); print(target)
def common(x): x.add_argument("--author",required=True)
ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
p=sub.add_parser("add"); p.add_argument("title"); p.add_argument("--project",required=True); p.add_argument("--due"); p.add_argument("--remind"); p.add_argument("--context"); p.add_argument("--source"); p.add_argument("--completion"); common(p); p.set_defaults(fn=add)
for n in ("list","due"):
 p=sub.add_parser(n); p.add_argument("--project"); p.add_argument("--before"); p.set_defaults(fn=listing)
p=sub.add_parser("show"); p.add_argument("task_id"); p.set_defaults(fn=show)
p=sub.add_parser("edit"); p.add_argument("task_id"); [p.add_argument("--"+x) for x in ("title","project","due","remind","context","completion")]; common(p); p.set_defaults(fn=edit)
for n,done in (("done",True),("reopen",False)):
 p=sub.add_parser(n); p.add_argument("task_id"); common(p); p.set_defaults(fn=lambda a,d=done:move(a,d))
a=ap.parse_args(); a.fn(a)

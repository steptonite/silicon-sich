#!/usr/bin/env python3
"""Ручний refresh живих джерел. Автозапуск цей скрипт не встановлює."""
import subprocess, sys
from datetime import datetime
from pathlib import Path
from sb_config import CFG, P

jobs=[("claude-code",CFG.get("live_sources",{}).get("claude_code_sessions",""),CFG["archives"].get("claude_code","")),("codex",CFG.get("live_sources",{}).get("codex_sessions",""),CFG["archives"].get("codex",""))]
results=[]; failed=False; adapter=Path(__file__).with_name("archive_sessions.py")
for label,src,out in jobs:
    if not src or not P(src).exists(): results.append(f"{label}: source absent, skipped"); continue
    p=subprocess.run([sys.executable,str(adapter),"--source",str(P(src)),"--out",str(P(out)),"--label",label],capture_output=True,text=True)
    failed |= p.returncode!=0; results.append((p.stdout or p.stderr).strip())
line=f"[{datetime.now():%d.%m.%Y %H:%M}] "+" | ".join(results); print(line)
log=CFG.get("maintenance",{}).get("log_path")
if log:
    lp=P(log); lp.parent.mkdir(parents=True,exist_ok=True)
    with lp.open("a",encoding="utf-8") as f: f.write(f"- {line}\n")
raise SystemExit(1 if failed else 0)

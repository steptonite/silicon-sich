#!/usr/bin/env python3
"""Incremental local agent JSONL → immutable raw + readable Markdown."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


def content_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            item.get("text", "") for item in value
            if isinstance(item, dict) and item.get("type") in {"text", "input_text", "output_text"}
        )
    return ""


def extract_turns(path: Path) -> list[tuple[str, str]]:
    turns = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = obj.get("message") if isinstance(obj.get("message"), dict) else obj
        role = message.get("role")
        if role not in {"user", "assistant"}:
            payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
            role = payload.get("role")
            message = payload if role in {"user", "assistant"} else message
        if role not in {"user", "assistant"}:
            continue
        text = content_text(message.get("content")).strip()
        if text:
            turns.append((role, text))
    return turns


def title(turns: list[tuple[str, str]]) -> str:
    for role, text in turns:
        if role == "user":
            return " ".join(text.split())[:100]
    return "Agent session"


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-zА-Яа-яІіЇїЄєҐґ0-9]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_")[:55] or "Agent_session"


def render(label: str, source_id: str, day: str,
           turns: list[tuple[str, str]]) -> str:
    heading = title(turns)
    lines = [
        "---", f"source: {label}", f"created: {day}",
        f"source_file_id: {source_id}", "status: raw", "---", "",
        f"# {heading}", "",
        "> ⚠️ Сира локальна сесія; не куроване знання.", "",
    ]
    names = {"user": "🧑 User", "assistant": "🤖 Assistant"}
    for role, text in turns:
        lines += [f"## {names[role]}", "", text, ""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    source = args.source.expanduser()
    out = args.out.expanduser()
    md, raw = out / "md", out / "raw"
    state_file = out / "state.json"
    md.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    changed = 0
    for path in sorted(source.rglob("*.jsonl")) if source.exists() else []:
        key = str(path.resolve())
        signature = f"{path.stat().st_mtime_ns}:{path.stat().st_size}"
        if state.get(key) == signature:
            continue
        turns = extract_turns(path)
        if not turns:
            continue
        source_id = hashlib.sha256(key.encode()).hexdigest()[:12]
        day = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
        name = f"{day}_{slug(title(turns))}_{source_id}.md"
        raw_target = raw / f"{source_id}.jsonl"
        raw_target.write_bytes(path.read_bytes())
        (md / name).write_text(
            render(args.label, source_id, day, turns), encoding="utf-8"
        )
        state[key] = signature
        changed += 1
    temp = state_file.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    temp.replace(state_file)
    print(json.dumps({"source": args.label, "changed": changed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

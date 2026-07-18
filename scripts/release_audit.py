#!/usr/bin/env python3
"""Fail closed when a distributable Kit tree contains likely secrets or PII."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


DEFAULT_EXCLUDES = {".git", ".venv", "__pycache__"}
TEXT_SUFFIXES = {
    ".md", ".py", ".sh", ".toml", ".json", ".yaml", ".yml", ".txt",
}
PATTERNS = {
    "OpenRouter key": re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{20,}\b"),
    "OpenAI key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    "absolute user path": re.compile(
        r"/Users/(?!USER(?:/|$)|name(?:/|$)|<user>(?:/|$))[^/\s\"']+"
    ),
    "home email": re.compile(r"\b[A-Z0-9._%+-]+@(?!example\.com\b)[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
}


def audit(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in DEFAULT_EXCLUDES for part in path.parts):
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {".gitignore"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(root)
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{rel}:{line}: {label}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=Path(__file__).parents[1], type=Path)
    args = parser.parse_args()
    findings = audit(args.root.resolve())
    if findings:
        print("RELEASE AUDIT FAILED")
        print("\n".join(f"  {item}" for item in findings))
        return 1
    print("RELEASE AUDIT OK: секретів і персональних маркерів не знайдено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

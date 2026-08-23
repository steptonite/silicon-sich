#!/usr/bin/env python3
"""Fail closed when a distributable Kit tree contains likely secrets or PII."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


DEFAULT_EXCLUDES = {".git", ".venv", "__pycache__"}
TEXT_SUFFIXES = {
    ".md", ".py", ".sh", ".toml", ".json", ".yaml", ".yml", ".txt",
    ".html", ".csv", ".ipynb", ".xml", ".tsv",
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


def _is_detector(line: str) -> bool:
    """Чи є цей рядок визначенням шаблону пошуку, а не даними."""
    return "re.compile(" in line or "grep -" in line


def audit(root: Path) -> tuple[list[str], list[str]]:
    findings: list[str] = []
    unreadable: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in DEFAULT_EXCLUDES for part in path.parts):
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        rel = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            tag = (
                "текстовий суфікс, але не UTF-8"
                if path.suffix.lower() in TEXT_SUFFIXES
                else "нетекстовий файл"
            )
            unreadable.append(f"{rel} ({tag})")
            continue
        lines = text.splitlines()
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                # Рядок, який САМ Є визначенням детектора, — не витік, а
                # інструмент. doctor.sh шукає чужі абсолютні шляхи регексом
                # /Users/[A-Za-z]+ і через це ловився власним же аудитом.
                # Виняток структурний (за формою рядка), а не за іменем файлу:
                # білий список по імені пропустив би наступний такий детектор.
                if _is_detector(lines[line - 1] if line <= len(lines) else ""):
                    continue
                findings.append(f"{rel}:{line}: {label}")
    return findings, unreadable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=Path(__file__).parents[1], type=Path)
    args = parser.parse_args()
    findings, unreadable = audit(args.root.resolve())
    if unreadable:
        print("WARNING: файли не проскановано (не читаються як UTF-8 текст) — перевір руками:")
        print("\n".join(f"  {item}" for item in unreadable))
    if findings:
        print("RELEASE AUDIT FAILED")
        print("\n".join(f"  {item}" for item in findings))
        return 1
    print("RELEASE AUDIT OK: секретів і персональних маркерів не знайдено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

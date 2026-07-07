#!/usr/bin/env python3
"""sb_config.py — спільний лоадер конфігурації Second Brain Kit.

Порядок пошуку config.toml:
  1. env SB_CONFIG=/шлях/до/config.toml (зручно для тестів)
  2. config.toml поруч із цим файлом (scripts/config.toml)
  3. ~/.config/second-brain/config.toml
Нема жодного → зрозуміла помилка з підказкою скопіювати config.example.toml.

Використання:
    from sb_config import CFG, P
    memory_dir = P(CFG["vault"]["memory"])   # Path із розгорнутим ~
"""
from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent


def P(s: str) -> Path:
    """Рядок конфіга → Path із розгорнутим ~."""
    return Path(s).expanduser()


def _find_config() -> Path:
    cand = []
    env = os.environ.get("SB_CONFIG")
    if env:
        cand.append(Path(env).expanduser())
    cand.append(HERE / "config.toml")
    cand.append(Path.home() / ".config" / "second-brain" / "config.toml")
    for c in cand:
        if c.exists():
            return c
    sys.exit(
        "ERROR: не знайдено config.toml.\n"
        f"Скопіюй {HERE / 'config.example.toml'} → {HERE / 'config.toml'} "
        "і відредагуй шляхи (або задай SB_CONFIG=/шлях/до/config.toml)."
    )


def load() -> dict:
    path = _find_config()
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    cfg["_config_path"] = str(path)
    return cfg


CFG = load()

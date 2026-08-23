#!/usr/bin/env python3
"""Ціна дії називається ДО дії, а не в рахунку.

Привід (Льоша, 23.08.2026): у першої ж людини з платною копією згоріли гроші на
операціях, вартість яких вона побачила постфактум — «побудова графа зʼїла майже
стільки ж, скільки установка». Правило в базі було давно; у продукті його не було.

Тому кожен платний прогін ембедера спершу МІРЯЄ роботу (скільки файлів реально
змінилось, скільки чанків доведеться порахувати, скільки це символів) і називає
очікувану ціну. Дорого — питає. Не може спитати (не термінал) — зупиняється.

🔴 Три речення, які тут закодовані:
  1. Мовчки платити не можна НІКОЛИ. Мовчки не працювати — можна.
  2. Оцінка робиться по РЕАЛЬНІЙ роботі (пропущені незмінені файли не коштують),
     а не по розміру вольта — інакше вона лякає дарма і її перестають читати.
  3. Ставка може застаріти. Тому вона в конфізі, а в тексті стоїть слово
     «оцінка» і назва ставки — щоб людина могла звірити з рахунком.
"""
from __future__ import annotations

import os
import sys

# ⚠️ Ставка НЕ звірена з прайсом станом на 23.08.2026 — це порядок величини,
#    щоб число існувало взагалі. Уточнюється в config.toml: embed.price_per_mtok.
DEFAULT_PRICE_PER_MTOK = 0.01     # $ за 1 млн токенів
CHARS_PER_TOKEN = 4               # груба, але стабільна оцінка для кирилиці+латиниці
DEFAULT_CONFIRM_OVER = 0.05       # $ — вище цього питаємо дозволу


def estimate(n_chunks: int, n_chars: int) -> dict:
    """Рахуємо ЧИСЛА, а не тримаємо тексти: на великому вольті список чанків
    у памʼяті коштує дорожче за саму перевірку."""
    return {"chunks": int(n_chunks), "chars": int(n_chars),
            "tokens": int(n_chars) // CHARS_PER_TOKEN}


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def price(est: dict, rate: float) -> float:
    return est["tokens"] / 1_000_000 * rate


def gate(est: dict, *, engine: str, what: str, cfg: dict,
         assume_yes: bool = False) -> None:
    """Пропустити, зупинити або спитати. Виходить із процесу, якщо не дозволено."""
    if est["chunks"] == 0:
        return
    if engine != "openrouter":          # локально — безкоштовно, мовчимо
        return
    rate = float(cfg.get("price_per_mtok", DEFAULT_PRICE_PER_MTOK))
    limit = float(cfg.get("confirm_over_usd", DEFAULT_CONFIRM_OVER))
    usd = price(est, rate)
    shard = _plural(est["chunks"], "шматок", "шматки", "шматків")
    head = (f"\n💸 ПЛАТНА ОПЕРАЦІЯ: {what}\n"
            f"   обсяг: {est['chunks']} {shard} · ~{est['tokens']:,} токенів\n"
            f"   оцінка: ${usd:.4f} за ставкою ${rate}/1М токенів "
            f"(ставка з config.toml → embed.price_per_mtok; звір із рахунком)\n"
            f"   безкоштовна альтернатива: підняти Ollama (`ollama serve`) — $0")
    if usd < limit or assume_yes:
        print(head + ("\n   → дозволено прапорцем --yes" if assume_yes else
                      f"\n   → нижче порога ${limit} — роблю без питання"), file=sys.stderr)
        return
    if not sys.stdin.isatty():
        sys.exit(head + "\n🔴 Спитати нема в кого (не термінал), а мовчки платити не можна.\n"
                        "   Дозволити свідомо: додай --yes до команди.")
    print(head, file=sys.stderr)
    if input("   Продовжити? [y/N] ").strip().lower() not in ("y", "yes", "т", "так"):
        sys.exit("   Зупинено. Нічого не витрачено.")


def cfg_from(embed_cfg: dict) -> dict:
    return {"price_per_mtok": embed_cfg.get("price_per_mtok", DEFAULT_PRICE_PER_MTOK),
            "confirm_over_usd": embed_cfg.get("confirm_over_usd", DEFAULT_CONFIRM_OVER)}


if __name__ == "__main__":
    e = estimate(25, 100_000)
    print(e, "≈", f"${price(e, DEFAULT_PRICE_PER_MTOK):.4f}")

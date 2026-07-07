# 01 — Експорт чатів (🙋 крок людини)

Модель цього зробити не може — потрібні акаунти людини. Дай людині ці інструкції
дослівно. Усі три сервіси надсилають архів на email (від хвилин до доби).

## ChatGPT

1. chatgpt.com → аватар → **Settings** → **Data controls** → **Export data**.
2. Лист «Your data export is ready» → скачати zip.
3. Усередині головне: `conversations.json` (усі розмови) і
   `conversation_asset_file_names.json` (людські імена вкладень). Медіа-файли
   конвертер не копіює — тільки згадує за іменем.

## Gemini (Google Takeout)

1. takeout.google.com → **Deselect all** → увімкнути **My Activity** (у ньому
   обрати «Gemini Apps»), **NotebookLM** (якщо є зошити), **Gemini in Workspace** (якщо є).
2. Export once → скачати zip, розпакувати.
3. Ключовий файл: `Takeout/My Activity/Gemini Apps/MyActivity.html` — плаский
   журнал prompt→response (Google не віддає структуру розмов; конвертер сам
   реконструює сесії за розривами в часі).

## Claude

1. claude.ai → ініціали → **Settings** → **Privacy** → **Export data**.
2. Лист → zip. Усередині: `conversations.json`, `projects/*.json`,
   `design_chats/*.json` (якщо були), `memories.json` (профіль, який Claude сам
   накопичив — цінний сид для дистиляції).

## Куди класти

У будь-які теки поза vault (напр. `~/exports/chatgpt-2026-07/`). Сирі zip/розпаковки
НЕ видаляти — це першоджерело нульового шару. Наступні експорти — просто нові теки;
конвертери ідемпотентні й доконвертують лише нове.

# 04 — Семантичний індекс (librarian)

## Стек

- **bge-m3** — багатомовна embedding-модель (1024-вим), перетворює текст на вектори сенсу.
- **sqlite-vec** — векторний індекс в одному файлі `index.db` (WAL — кілька писців
  одночасно не ламають базу). Жодного сервера баз даних.

## Де ганяти embed: два рівноцінні варіанти

Обидва використовують ТУ САМУ модель bge-m3 → вектори сумісні: можна почати з A,
пізніше перейти на B (чи навпаки) БЕЗ переіндексації. Вибір — у `config.toml [embed]`.

**Варіант A — OpenRouter (найпростіший старт).** Нічого не встановлюєш локально:
`openrouter_enabled = true` + ключ (env `OPENROUTER_API_KEY` або файл `env_file`).
Ціна копійчана (~$0.01/M токенів — повна індексація тисяч чатів коштує центи).
Мінус: текст чанків їде в хмару на embed. Бери цей варіант, якщо «складно з Ollama»
або машина слабка.

**Варіант B — локальний Ollama ($0, приватно).** Чати не покидають машину, кожен
запит безкоштовний; тягне навіть Mac M-серії з 8 ГБ. Постав [Ollama](https://ollama.com)
і модель: `ollama pull bge-m3` (≈1.1 ГБ разово). 🙋 На macOS керувати Ollama-моделями
(старт/стоп, які моделі стоять) зручно через GUI-панель
[KobzarAI](https://github.com/steptonite/KobzarAI) — не треба чіпати термінал.

Логіка `--backend auto` (дефолт): якщо Ollama живий — він; якщо ні і OpenRouter
ввімкнено — OpenRouter; якщо ні те, ні те — зрозуміла помилка з двома виходами.

## Команди

```bash
PY=<kit>/.venv/bin/python
$PY scripts/librarian.py index --source all        # перший прогін; далі інкрементно по sha
$PY scripts/librarian.py index --source memory     # після запису нот — миттєво
$PY scripts/librarian.py search "запит ПО СЕНСУ" -k 8 [--source memory|chatgpt|…]
$PY scripts/librarian.py search "точний короткий термін" --retrieval keyword
$PY scripts/librarian.py search "останнє рішення" --after 2026-07-01 --prefer-recent
$PY scripts/librarian.py search "запит" --format json  # контракт для хуків/агентів
$PY scripts/librarian.py stats
```

Search віддає сніпети з джерелом+файлом+дистанцією (менша = ближче). Це і є
«пригадування»: модель читає 3–8 сніпетів замість того, щоб тягнути в контекст
цілі архіви — головна механіка економії токенів.

## Hybrid retrieval (дефолт)

`hybrid` збирає dense-кандидатів bge-m3 і keyword-кандидатів SQLite FTS5/BM25,
зливає ранги через weighted RRF (`k=60`) і потім застосовує authority/trust.
Rollback без міграції: `--retrieval vector`; точна legacy-видача без diversity cap:
`--retrieval vector --max-per-file 0`. Keyword-діагностика:
`--retrieval keyword`.

Видача робить exact-dedup і soft per-file cap: спершу один чанк на файл, потім
другий; якщо корпус вузький, cap не скорочує `-k`. Керування: `--max-per-file N`,
`0` вимикає. Сирі чати мають trust penalty у загальному пошуку, але всередині
`--source chatgpt|transcript|…` їхній взаємний порядок зберігається.

Перший запуск після оновлення створює FTS5 і backfill metadata без повторного embed.
`chunks`, `vchunks` і `chunks_fts` мають однакову кількість рядків.

## Час і superseded

Файлова дата береться з frontmatter, потім з імені, потім як перша явна дата у вступі
документа; `mtime` — лише слабкий fallback.
Він показується, але не проходить `--after/--before` і не отримує recency boost без
`--include-undated`. Без temporal-прапорців час не змінює ранг.

Параметри: `--after`, `--before`, `--include-undated`, `--prefer-recent`,
`--include-superseded`. `status: superseded|deprecated` прихований за замовчуванням;
`superseded_by:` показує наступний канон. Це metadata документа, не вгадування того,
що людина передумала всередині сирої розмови.

## JSON-контракт

`--format json` повертає `source/ref/chunk_idx/snippet`, vector/keyword ranks,
fusion score, confidence, дату+її джерело, status, warnings і exact alternates.
Хуки читають JSON, а не парсять декоративний текст regex-ами.

## Ранжування: курований шар ПЕРЕМАГАЄ сирий

Десятки тисяч сирих чат-чанків завжди «перекричать» жменю самарі, якщо ранжувати
чесно по дистанції. Тому `SOURCE_WEIGHT` — множник до дистанції (<1 = вище):
knowledge 0.82 · memory 0.85 · NotebookLM 0.85 · сирі чати 1.0 · транскрипти 1.05.
Без цього «ланцюг знань» — декларація, а не поведінка.

## Банери недовіри

Сирі джерела (chatgpt/gemini/claude/inbox/transcript) виходять із банером
`⚠️ НЕ верифіковано` — модель, що читає видачу, зобов'язана ставитись до них як до
підказки «де шукати», а не як до факту. Курований шар (knowledge, memory,
NotebookLM) — без банера.

## Що НЕ індексується

- `MEMORY.md` (індекс, не зміст) і `_INBOX.md` (інструкція).
- 💭-callout-блоки (thinking моделей) — вирізаються перед індексацією:
  думки моделі — найменш надійний шар, їм нічого робити в топі видачі.

## Обслуговування

- Після кожного запису memory-ноти: `index --source memory` (секунди).
- Після нового експорту: `index --source <джерело>` (інкрементно).
- PreCompact-хук сам фоново доіндексовує транскрипти сесій.
- `stats` — здоров'я індексу (чанки по джерелах, розмір .db).

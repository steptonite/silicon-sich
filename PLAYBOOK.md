# PLAYBOOK — покрокова побудова Другого мозку

> **Кому адресовано: тобі, Клоде** (або іншій моделі-агенту в Claude Code). Людина поруч
> лише спостерігає і робить кроки, позначені 🙋 (експорти даних, установка застосунків,
> апруви). Виконуй етапи ПО ЧЕРЗІ; кожен закінчується блоком «✅ Перевірка» — не йди далі,
> поки перевірка не пройшла. Перед стартом прочитай [docs/00-philosophy.md](docs/00-philosophy.md)
> і [docs/07-model-discipline.md](docs/07-model-discipline.md) — друге визначає, ЯК ти працюєш
> протягом усієї побудови, не тільки після неї. І паралельно з побудовою НАВЧАЙ людину
> системі за [docs/09-teaching.md](docs/09-teaching.md) — по одному поняттю на етап,
> показом, а не лекцією; після етапу 7 проведи фінальний 15-хвилинний тур звідти ж.
> Якщо ти НЕ Claude Code (Codex, Gemini CLI…) — спершу [docs/10-portability.md](docs/10-portability.md):
> дані працюватимуть одразу, але шар дисципліни (хуки) потребує адаптера.

## Мапа системи (що будуємо)

```
Експорти чатів (ChatGPT/Gemini/Claude)         🙋 людина скачує
        │  convert_*.py
        ▼
MD-архіви (1 чат = 1 файл з датою + _INDEX)     сирий шар, IMMUTABLE
        │  дистиляція (окремий етап)
        ▼
_KNOWLEDGE/_TOPICS + memory-граф                курований шар (нотатки-факти)
        │  symlinks
        ▼
Obsidian master-vault (один граф для людини)
        │  librarian.py index
        ▼
Семантичний індекс (sqlite-vec + bge-m3, $0)
        │  хуки харнеса
        ▼
Claude, який ПАМ'ЯТАЄ: авто-пригадування на кожне повідомлення,
memory-lint на кожен запис, bridge між сесіями
```

Метафора для людини: сирі чати = **склад**, дистиляція = **бібліотечний каталог**,
семантика = **бібліотекар, що розуміє питання по сенсу**, граф = **стежки між полицями**.

---

## Етап 0 — Середовище

**Передумови:** macOS/Linux, Python ≥ 3.11, Claude Code.
**Дії:**
1. 🙋 Людина: установити [Obsidian](https://obsidian.md).
2. 🙋 Спитай людину, який embed-рушій для семантики (обидва рівноцінні, [docs/04](docs/04-semantics.md)):
   - **A — OpenRouter** (найпростіше, нічого не ставити): людина дає API-ключ, ти вмикаєш `openrouter_enabled=true` у config.
   - **B — локальний Ollama** ($0, приватно): людина ставить [Ollama](https://ollama.com); на macOS керувати моделями зручно через GUI [KobzarAI](https://github.com/steptonite/KobzarAI).
3. Запусти `bash scripts/setup.sh`. Перший прогін створить `scripts/config.toml` — відредагуй шляхи під цю машину (єдине місце шляхів, див. коментарі в файлі) і секцію `[embed]` під обраний варіант. Запусти setup ще раз: він створить venv, теки і symlinks (для варіанта B — ще й стягне bge-m3, ≈1.1 ГБ разово).

**✅ Перевірка:** `scripts/setup.sh` завершується рядком «Готово»; embed живий: варіант B — `curl -s localhost:11434/api/tags | grep bge-m3` щось знаходить; варіант A — `openrouter_enabled=true` у config і ключ на місці (env або env_file).

## Етап 1 — Експорт чатів (🙋 повністю людина)

Дай людині інструкції з [docs/01-export.md](docs/01-export.md): ChatGPT → Settings → Export data; Gemini → Google Takeout; Claude → Settings → Export data. Експорти приходять на email як zip. Людина розпаковує їх у будь-які теки і каже тобі шляхи.

**✅ Перевірка:** у теці ChatGPT-експорту є `conversations.json`; у Takeout є `My Activity/Gemini Apps/MyActivity.html`; у Claude-експорті є `conversations.json`.

## Етап 2 — Конверсія в Markdown

Один чат = один MD-файл з датою в імені (чати — це інформація В ЧАСІ). Конвертери ідемпотентні: наступний експорт доконвертує лише нове. Деталі і як адаптувати під нове джерело — [docs/02-convert.md](docs/02-convert.md).

```bash
python3 scripts/convert_chatgpt.py --src <експорт> --out <archives.chatgpt з config> --user-label Ім'я
python3 scripts/convert_gemini.py  --takeout <Takeout> --out <archives.gemini> --user-label Ім'я
python3 scripts/convert_claude.py  --src <експорт> --out <archives.claude> --user-label Ім'я
```

**✅ Перевірка:** у кожному архіві з'явились `chats/*.md` + `_INDEX.md`; відкрий 2-3 файли — текст читабельний, thinking/tool-шум у згорнутих callout. `[done]`-рядок конвертера без помилок. 🔴 Сирі архіви з цього моменту **IMMUTABLE** — лише читати.

## Етап 3 — Memory-граф + Obsidian master-vault

Ядро системи — тека memory: **одна нота = один факт**, плаский список, snake_case-імена з префіксами (`project_`, `ref_`, `feedback_`, `issue_`, `user_`, `idea_`, `hub_`). Канон — [templates/canon.md](templates/canon.md), шаблон ноти — [templates/memory-note.template.md](templates/memory-note.template.md).

**Дії:**
1. Скопіюй шаблони в memory-теку: `MEMORY.md` (індекс), `bridge.md`, `_HOME.md` + 2-4 стартові хаби `hub_*` під домени життя людини (спитай людину, які в неї домени: робота/проєкти/здоров'я/гроші…).
2. Створи vault: symlinks уже зробив setup.sh (Етап 0). 🙋 Людина відкриває `vault.root` як Obsidian-vault і бачить один граф.
3. Заведи `log.md` у vault-корені ([templates/log.md.template](templates/log.md.template)) — append-only журнал операцій.

Деталі — [docs/03-vault.md](docs/03-vault.md).

**✅ Перевірка:** Obsidian відкриває vault, graph view показує і memory, і архіви; `python scripts/sanitize.py --audit` → 0 порушень.

## Етап 4 — Семантичний індекс

```bash
.venv/bin/python scripts/librarian.py index --source all   # перший прогін довгий (хвилини-години на великих архівах)
.venv/bin/python scripts/librarian.py stats
.venv/bin/python scripts/librarian.py search "тема з минулих чатів людини" -k 5
```

Embed — обраним на Етапі 0 рушієм (Ollama = $0 приватно / OpenRouter = центи). Індекс інкрементний по sha — наступні прогони копійчані. Деталі, ваги джерел і банери недовіри — [docs/04-semantics.md](docs/04-semantics.md).

**✅ Перевірка:** `search` знаходить чат ПО СЕНСУ (спитай людину про тему, якої НЕМАЄ дослівно в тексті — синонімами), у видачі стоять банери ⚠️ на сирих джерелах.

## Етап 5 — Хуки харнеса (дисципліна в залізі)

Чотири хуки переносять дисципліну з «пам'ятай, будь ласка» в механіку — [docs/05-hooks.md](docs/05-hooks.md):

| Хук | Подія | Що робить |
|---|---|---|
| semantic_recall | UserPromptSubmit | авто-пошук по базі на кожне повідомлення → топ-3 збіги в контекст |
| memory_lint | PostToolUse Write/Edit | нота порушує канон → негайний чек-ліст що дофіксити |
| pre_compact | PreCompact | фонова доіндексація сесії ПЕРЕД стисненням контексту |
| session_start | SessionStart | інжект bridge.md («де спинились») + правила пам'яті |

**Дії:** візьми блок із `scripts/hooks/settings-hooks.example.json`, заміни `<KIT>` на абсолютний шлях кита, злий у `~/.claude/settings.json` (НЕ затри чужі хуки). 🙋 Людина перезапускає сесію Claude Code.

**✅ Перевірка:** нова сесія стартує з блоком «ВІДНОВЛЕННЯ СЕСІЇ»; повідомлення довше 30 символів приносить блок «🧠 АВТО-ПРИГАДУВАННЯ»; запис ноти без wikilinks повертає лінт-чекліст.

## Етап 6 — Дистиляція (сире ≠ знання)

Поверх сирих архівів будується курований шар: `_KNOWLEDGE.md` (тематичні самарі з провенансом) і `_TOPICS.md` (кластери). Це ОКРЕМА, найвідповідальніша робота — правила анти-галюцинації в [docs/06-distillation.md](docs/06-distillation.md): дата на кожному факті, версія інструмента, лінк на чат-джерело, «⚠️ неверифіковано» замість впевненої прози. Роби ітеративно, по кластеру за раз; після кожного — `index --source knowledge`.

**✅ Перевірка:** `search` по темі кластера підіймає самарі ВИЩЕ сирих чатів (вага knowledge 0.82); випадкові 3 факти з самарі мають дату+джерело, і джерело їх підтверджує.

## Етап 7 — Дисципліна в CLAUDE.md (постійна експлуатація)

Скопіюй [templates/CLAUDE.md.template](templates/CLAUDE.md.template) у `~/.claude/CLAUDE.md` (або злий з наявним). Це «залізні правила»: пошук-перед-твердженням, запис-одразу-з-доказом, дати всюди, епістемічні маркери, поведінка при лімітах. Повне пояснення КОЖНОГО правила і як моделі себе дресирувати — [docs/07-model-discipline.md](docs/07-model-discipline.md).

**✅ Перевірка (живий тест):** у новій сесії спитай модель про факт із старого чату — вона мусить СПОЧАТКУ викликати librarian search, потім відповісти з маркером 📚 і назвою джерела.

---

## Постійний цикл після побудови

- Новий експорт раз на місяць-два → Етап 2 (доконвертує нове) → `index --source <джерело>`.
- Кожен новий факт/рішення → memory-нота одразу (лінт-хук простежить за каноном).
- Сирі надиктовки людини → `inbox/` → розфасування в ноти (`status: processed`, першоджерело не видаляти).
- Раз на тиждень-два: `sanitize.py --audit` + погляд людини на graph view.
- Кожна операція над бібліотекою → рядок у `log.md`.

Щось пішло не так → [docs/08-troubleshooting.md](docs/08-troubleshooting.md).

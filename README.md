# Second Brain Kit

> **V1 — безкоштовний стабільний starter kit.** Ця гілка отримує лише
> security, data-loss і compatibility fixes. Нові можливості, guided installer,
> міграції та підтримка Claude/Codex розвиваються у приватному SecondBrainKit V2.
> До відкриття продажів V2 використовуйте цей репозиторій і стежте за
> оголошеннями автора.

Відтворюваний набір для побудови **персонального «другого мозку»** навколо Claude:
усі ваші чати з ChatGPT/Gemini/Claude перетворюються на локальну базу знань з
семантичним пошуком, Obsidian-графом і моделлю, яка справді пам'ятає — між сесіями,
компактами й акаунтами.

**Виконавець — модель (Claude в Claude Code), людина лише спостерігає** і робить
кілька ручних кроків (скачати експорти, поставити Obsidian, апрувнути).

## Що отримуєте

- 📦 Lossless MD-архів усіх ваших чатів (1 розмова = 1 файл, читається в Obsidian)
- 🔎 Семантичний пошук по СЕНСУ (bge-m3 + sqlite-vec; рушій на вибір — хмарний
  OpenRouter за копійки або локальний Ollama за $0)
- 🕸 Один Obsidian-граф: нотатки-факти + архіви + зв'язки
- 🤖 Клод із дисципліною пам'яті: авто-пригадування на кожне повідомлення (хук),
  лінт нотаток у момент запису (хук), міст між сесіями (bridge.md)
- 📉 Економію токенів: у контекст їдуть 3 сніпети, а не тонни історії
- ✅ Локальні Markdown-задачі: `tasks/active` → незмінний `archive/YYYY-MM`
- 🔄 Ручний інкрементальний refresh локальних Claude Code/Codex сесій
- 🧪 Перевірку курованих нот на дати, провенанс і чесне маркування невпевненості

Метафора: сирі чати — **склад** → дистиляція — **каталог** → семантика —
**бібліотекар, що розуміє питання** → граф — **стежки між полицями**.

## Швидкий старт

1. Відкрий цю теку в Claude Code і скажи моделі: **«Виконуй PLAYBOOK.md»**.
2. Далі вона вестиме процес сама і казатиме, де потрібні твої 🙋-кроки.

Ручний шлях — той самий [PLAYBOOK.md](PLAYBOOK.md), етапи 0–7.

## Карта репо

```
PLAYBOOK.md            ← ГОЛОВНЕ: покрокова інструкція для моделі-виконавця
CHECKLIST-HUMAN.md     ← коротко: що робить людина
docs/                  ← глибина по кожному етапу
  00-philosophy        02-convert          05-hooks           07-model-discipline
  01-export            03-vault            06-distillation    08-troubleshooting
                       04-semantics        09-teaching (як навчати людину системі)
                                           10-portability (Codex та інші агенти)
  11-tasks · 12-live-refresh · 13-library-maintenance
scripts/               ← робочі інструменти (конфіг шляхів: config.example.toml)
  setup.sh · convert_chatgpt.py · convert_gemini.py · convert_claude.py
  librarian.py · task.py · brain_refresh.py · archive_sessions.py
  distill_delta.py · sanitize.py · hooks/
templates/             ← CLAUDE.md, канон vault, шаблони нот/хабів/bridge
fixtures/              ← синтетичні міні-експорти для перевірки скриптів
```

## Три різні шари

- `inbox/` — сирі думки й надиктовки, які ще треба класифікувати.
- `tasks/` — підтверджені дії зі станом, строком і completion condition.
- `memory/` та `knowledge/` — довготривалі факти, рішення й куровані висновки.

Не перетворюйте кожну ідею на задачу, а завершену задачу — автоматично на знання.
Деталі: [docs/11-tasks.md](docs/11-tasks.md).

## Вимоги

macOS або Linux · Python ≥ 3.11 · [Obsidian](https://obsidian.md) · Claude Code.

Для семантики — ОДИН із двох рушіїв на вибір ([docs/04](docs/04-semantics.md)):
- **OpenRouter** (найпростіше): лише API-ключ, ціна копійчана; або
- **[Ollama](https://ollama.com)** (модель bge-m3, ≈1.1 ГБ): локально, $0, приватно.
  На macOS керувати Ollama зручно через GUI [KobzarAI](https://github.com/steptonite/KobzarAI).

## Перевірка кита без своїх даних

```bash
bash scripts/setup.sh
python3 scripts/convert_chatgpt.py --src fixtures/chatgpt-sample --out /tmp/sb-demo/chatgpt-archive
```

— у `/tmp/sb-demo` з'являться готові MD-нотатки з синтетичних розмов.

## Підтримка й ліцензія

- V1 можна безкоштовно використовувати для власної особистої або професійної
  роботи.
- Перепродаж, перепакування, публічне поширення копій і включення у сторонні
  продукти заборонені; повні умови — [LICENSE.md](LICENSE.md).
- Перед публічним релізом запускайте
  `.venv/bin/python scripts/release_audit.py`.

# 02 — Конверсія експортів у Markdown

## Канон конверсії (спільний для всіх джерел)

- **Один чат = один .md-файл.** Ім'я: `YYYY-MM-DD_Слаг_назви_shortid.md` — дата
  попереду, бо чати є інформацією В ЧАСІ (сортування тек = хронологія життя).
- **Lossless по тексту:** user/assistant — чисте тіло; thinking/reasoning/tool-вивід —
  у ЗГОРНУТИХ Obsidian-callout (`> [!note]- 💭 …`) — збережено, але не заважає читати
  і НЕ індексується (librarian вирізає 💭-блоки: думки моделі — найменш надійний шар).
- **Медіа не копіюємо** (гігабайти пікселів марні для тексту) — лишаємо згадку за іменем.
- **Frontmatter з hash** — конвертери ідемпотентні: незмінені файли не перезаписуються,
  наступний експорт доконвертовує лише нове (і індекс доіндексовує лише нове).
- **`_INDEX.md`** — автогенерована точка входу (таблиця всіх розмов по датах).
  Генерується, тому ре-конверсія її не «затре» — не редагуй її руками.

## Команди

```bash
python3 scripts/convert_chatgpt.py --src ~/exports/chatgpt --out <archives.chatgpt> --user-label Ім'я
python3 scripts/convert_gemini.py  --takeout ~/exports/Takeout --out <archives.gemini> --user-label Ім'я
python3 scripts/convert_claude.py  --src ~/exports/claude --out <archives.claude> --user-label Ім'я
```

`--limit N` — тестовий прогін на перших N розмовах. `--user-label` — як підписувати
людину в заголовках (`## 🧑 Ім'я`).

## Особливості джерел

- **ChatGPT:** розмови — дерево (`mapping` + `current_node`); конвертер бере активну
  гілку. Голосові — позначка «🎙 голосове» (можна потім прогнати whisper-ом).
- **Gemini:** MyActivity.html — плаский журнал без розмов; конвертер реконструює
  сесії за розривом >60 хв або зміною доби. NotebookLM-зошити — КУРОВАНИЙ контент
  (окрема тека `notebooklm/`, ранжується вище в пошуку).
- **Claude:** гілки розмов зберігаються (відрізані — у згорнутому блоці «🌿 інша
  гілка»); `memories.json` → `memories.md`; проєкти з їхніми system prompt → `projects/`.

## Як додати НОВЕ джерело (Telegram, Notion, будь-що)

1. Отримай експорт від людини; поклади сире в окрему теку (нічого не видаляти).
2. Напиши `convert_<джерело>.py` за зразком трьох наявних, дотримуючи канон вище
   (дата в імені, frontmatter+hash, callout для шуму, `_INDEX.md`).
3. Додай шлях у `config.toml [archives]` і source у `librarian.py`
   (функція `gather_<джерело>` + запис у `GATHER` + вага в `SOURCE_WEIGHT` + банер
   у `UNVERIFIED_SRC`, якщо джерело сире + choices у CLI).
4. Symlink теки у vault-корінь → `index --source <нове>` → тестовий search.
5. Рядок у `log.md` (операція `structure`).

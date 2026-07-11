# 12. Живі локальні сесії

Хмарні експорти залишаються ручними. Для локальних JSONL-сесій Claude Code/Codex є
інкрементальний адаптер: raw-копія + коротка MD-обгортка з читабельним ім'ям
`YYYY-MM-DD_Назва_shortid.md`. Повторний прогін пропускає незмінені файли.

```bash
python scripts/brain_refresh.py
```

Відсутнє джерело пропускається; помилка адаптера дає non-zero. Скрипт не встановлює
launchd/cron. Розклад дозволено додати лише після явної згоди людини.

Сирі code-session MD можуть містити випадкові `[[wikilinks]]`. Symlink та semantic index
залишаються, але теки треба приховати у Obsidian `userIgnoreFilters`; у graph view додати
`-path:claude_code-archive -path:codex-archive`.

# 11 — Локальна task-система

Task state читається детерміновано через `task.py`, а librarian використовується
лише для пошуку задач за змістом.

```bash
python scripts/task.py add "Назва" --project work --due 31.12.2026 \
  --context "Навіщо" --completion "Коли справді завершено"
python scripts/task.py list
python scripts/task.py due
python scripts/task.py show task_20260718_001
python scripts/task.py edit task_20260718_001 --context "Новий контекст"
python scripts/task.py done task_20260718_001 --note "Результат"
python scripts/task.py reopen task_20260718_001
```

- `active/` містить відкриті задачі.
- `archive/YYYY-MM/` — завершену незмінну історію.
- `_TASKS.md` отримує автоматичний wikilink registry після кожної мутації.
- Ідея не стає задачею, доки користувач не підтвердив дію.

## Залежності між задачами

```bash
python scripts/task.py add "Зібрати монтаж" --depends-on task_20260718_001
python scripts/task.py edit task_20260718_002 --depends-on "task_..._001,task_..._003"
python scripts/task.py edit task_20260718_002 --depends-on none   # очистити
```

- `depends_on` — task_id через кому у frontmatter.
- `due` виводить задачу, чиї залежності ще **відкриті**, в окрему секцію `BLOCKED`,
  а не в робочу чергу — actionable лишається лише розблоковане.
- Виконана залежність (переїхала в `archive/`) автоматично знімає блок.
- id залежності, якого нема ніде (опечатка), не блокує, але кричить `BROKEN DEPS`.
- Руками зіпсована дата `due` не валить `list`/`due` — задача просто випадає з
  due-черги, лишаючись у `list`.

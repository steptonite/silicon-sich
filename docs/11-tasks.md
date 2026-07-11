# 11. Локальна task-система

`inbox` зберігає сире, `tasks` — підтверджену дію, `memory/knowledge` — довготривале знання.
Канонічний стан задачі живе у Markdown, не в чаті агента.

```bash
python scripts/task.py add "Перевірити демо" --project demo --due 15.07.2026 \
  --completion "Тест пройдено" --author "Назва моделі"
python scripts/task.py list --project demo
python scripts/task.py show task_YYYYMMDD_HHMMSS
python scripts/task.py edit task_YYYYMMDD_HHMMSS --due none --author "Назва моделі"
python scripts/task.py done task_YYYYMMDD_HHMMSS --author "Назва моделі"
python scripts/task.py reopen task_YYYYMMDD_HHMMSS --author "Назва моделі"
```

Завершення переносить файл з `active/` у `archive/YYYY-MM/`; reopen повертає його назад.
Історія не видаляється. Після кожної зміни `task.py` викликає `librarian index --source tasks`.
Якщо embed-сервіс тимчасово недоступний, Markdown-запис лишається канонічним.

#!/usr/bin/env python3
"""Persistent Markdown task store for ~/SecondBrain/tasks.

Exact task state is queried deterministically here. Semantic retrieval is handled by
librarian.py with source=tasks.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

from sb_config import CFG, P


def write_atomic(path: Path, text: str) -> None:
    """Запис у сусідній .tmp і підміна на місці.

    Порт із публічного репозиторію (PR #2, 20.07.2026), де цю дірку знайшли
    раніше: прямий write_text лишав обрізаний файл, якщо процес падав або
    скінчилось місце посеред запису. Задача — це стан людини; напівзаписана
    задача гірша за незаписану, бо виглядає як ціла.

    🔴 Правка два місяці жила ТІЛЬКИ у збірці й не існувала в джерелі — тобто
    наступна перезбірка мовчки зняла б її. Прийняв PR у публічний репозиторій —
    тим же ходом заводь у джерело.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


ROOT = P(CFG["vault"].get("tasks", "~/SecondBrain/tasks"))
ACTIVE = ROOT / "active"
ARCHIVE = ROOT / "archive"
DATE_FMT = "%d.%m.%Y"
DATETIME_FMT = "%d.%m.%Y %H:%M"
FIELDS = ("task_id", "type", "title", "project", "status", "created", "updated", "due", "remind_at", "source", "author", "depends_on")


def parse_deps(value: str) -> list[str]:
    """`depends_on` — task_id через кому. Порожнє/відсутнє → []. Нормалізуємо пробіли."""
    return [d.strip() for d in (value or "").split(",") if d.strip()]


def today() -> dt.date:
    return dt.datetime.now().astimezone().date()


def stamp() -> str:
    return dt.datetime.now().astimezone().strftime("%d.%m.%Y %H:%M")


def parse_date(value: str) -> dt.date:
    try:
        return dt.datetime.strptime(value, DATE_FMT).date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be DD.MM.YYYY") from exc


def parse_date_safe(value: str) -> dt.date | None:
    """Толерантний парс для СКАНУ вже збережених задач: руками зіпсована дата у
    frontmatter не має валити `list`/`due` (кит продає саме ручне редагування MD).
    None → викликач вирішує сам (у кінець сортування / пропустити з due-черги)."""
    try:
        return dt.datetime.strptime(value, DATE_FMT).date()
    except (ValueError, TypeError):
        return None


def parse_datetime(value: str) -> dt.datetime:
    try:
        return dt.datetime.strptime(value, DATETIME_FMT)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("datetime must be DD.MM.YYYY HH:MM") from exc


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def slugify(value: str, fallback: str = "task") -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9а-яіїєґ]+", "-", value, flags=re.IGNORECASE)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:70] or fallback


def ensure_dirs() -> None:
    ACTIVE.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"missing frontmatter: {path}")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError(f"unterminated frontmatter: {path}")
    data: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        data[key.strip()] = value
    return data, text[end + 5 :]


def render(data: dict[str, str], context: str, completion: str, history: list[str]) -> str:
    lines = ["---"]
    for key in FIELDS:
        value = data.get(key, "")
        lines.append(f"{key}: {yaml_quote(value)}")
    lines += ["---", "", f"# {data['title']}", "", "## Context", "", context.strip() or "—", "", "## Completion condition", "", completion.strip() or "—", "", "## History", ""]
    lines += history or [f"- {stamp()} · created · {data.get('author') or 'unknown'}"]
    return "\n".join(lines).rstrip() + "\n"


def body_sections(body: str) -> tuple[str, str, list[str]]:
    def section(name: str, next_name: str | None) -> str:
        start = body.find(f"## {name}\n")
        if start < 0:
            return ""
        start += len(f"## {name}\n")
        end = body.find(f"## {next_name}\n", start) if next_name else len(body)
        return body[start:end].strip()
    context = section("Context", "Completion condition")
    completion = section("Completion condition", "History")
    history_raw = section("History", None)
    history = [line for line in history_raw.splitlines() if line.strip().startswith("-")]
    return context, completion, history


def all_task_files() -> list[Path]:
    ensure_dirs()
    return sorted(ACTIVE.glob("*.md")) + sorted(ARCHIVE.glob("*/*.md"))


def find_task(task_id: str) -> Path:
    matches = []
    for path in all_task_files():
        try:
            data, _ = parse_frontmatter(path)
        except ValueError:
            continue
        if data.get("task_id") == task_id or data.get("task_id", "").startswith(task_id):
            matches.append(path)
    if not matches:
        raise SystemExit(f"ERROR: task not found: {task_id}")
    if len(matches) > 1:
        raise SystemExit(f"ERROR: task id is ambiguous: {task_id}")
    return matches[0]


def next_id() -> str:
    prefix = today().strftime("task_%Y%m%d_")
    nums = []
    for path in all_task_files():
        try:
            value = parse_frontmatter(path)[0].get("task_id", "")
        except ValueError:
            continue
        if value.startswith(prefix) and value[len(prefix):].isdigit():
            nums.append(int(value[len(prefix):]))
    return f"{prefix}{max(nums, default=0) + 1:03d}"


def sync_registry() -> None:
    """Перебудувати wikilink-реєстр у _TASKS.md (між registry-маркерами).

    Без нього task-файли — сироти Obsidian-графа (vault-lint 12.07.2026: 8/9).
    Лінк по basename — переживає переїзд active→archive."""
    index = ROOT / "_TASKS.md"
    if not index.exists():
        return
    rows = []
    for path in all_task_files():
        try:
            data, _ = parse_frontmatter(path)
        except ValueError:
            continue
        status = data.get("status", "?")
        mark = "✅" if status == "done" else "⬜️"
        rows.append(f"- {mark} [[{path.stem}|{data.get('title', path.stem)}]]")
    block = "<!-- registry:start -->\n\n## Реєстр задач (авто, task.py)\n\n" + "\n".join(rows) + "\n\n<!-- registry:end -->"
    text = index.read_text(encoding="utf-8")
    if "<!-- registry:start -->" in text:
        text = re.sub(r"<!-- registry:start -->.*?<!-- registry:end -->", lambda _: block, text, flags=re.S)
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    write_atomic(index, text)


def cmd_add(args: argparse.Namespace) -> None:
    ensure_dirs()
    task_id = next_id()
    data = {
        "task_id": task_id, "type": "task", "title": args.title.strip(),
        "project": slugify(args.project, "general"), "status": "open",
        "created": stamp(), "updated": stamp(), "due": args.due or "",
        "remind_at": args.remind or "", "source": args.source or "",
        "author": args.author or "unknown",
        "depends_on": ",".join(parse_deps(getattr(args, "depends_on", "") or "")),
    }
    filename = f"{today().isoformat()}_{slugify(args.title)}_{task_id}.md"
    path = ACTIVE / filename
    write_atomic(path, render(data, args.context or "", args.completion or "", []))
    sync_registry()
    print(f"CREATED {task_id}\nPATH {path}")


def load(path: Path) -> tuple[dict[str, str], str, str, list[str]]:
    data, body = parse_frontmatter(path)
    context, completion, history = body_sections(body)
    return data, context, completion, history


def cmd_list(args: argparse.Namespace) -> None:
    rows = []
    for path in all_task_files():
        data, _, _, _ = load(path)
        if args.status and data.get("status") != args.status:
            continue
        if args.project and data.get("project") != slugify(args.project):
            continue
        rows.append((data.get("status", ""), data.get("due", ""), data.get("task_id", ""), data.get("project", ""), data.get("title", "")))
    def sort_key(row: tuple[str, str, str, str, str]) -> tuple[bool, bool, dt.date, str]:
        status, due, task_id, _, _ = row
        due_date = (parse_date_safe(due) or dt.date.max) if due else dt.date.max
        return status != "open", due == "", due_date, task_id
    rows.sort(key=sort_key)
    if not rows:
        print("No tasks.")
        return
    for status, due, task_id, project, title in rows:
        print(f"{task_id}\t{status}\t{due or '-'}\t{project}\t{title}")


def cmd_due(args: argparse.Namespace) -> None:
    """Due/overdue задачі. Задача, чиї `depends_on` ще відкриті, не actionable —
    її виводимо окремою секцією BLOCKED, а не змішуємо з робочою чергою.

    Дві множини id: `open_ids` (ще не зроблені) і `all_ids` (усі, разом з архівом).
    `done` переносить файл в archive/, тож «нема серед open» = виконано → знято блок.
    Блокуємо ЛИШЕ на open-залежність. id, якого нема НІДЕ — битий (типо в task_id):
    не блокує (щоб не зависнути на опечатці), але попереджає окремим рядком."""
    boundary = parse_date(args.before) if args.before else today()
    # Прохід 1: id-множини + биті залежності по ВСІХ open (не лише в due-вікні — інакше
    # задача з опечаткою в dep і далеким due мовчала б до свого вікна).
    open_ids, all_ids, deps_by_open = set(), set(), []
    for path in all_task_files():
        try:
            data, _ = parse_frontmatter(path)
        except ValueError:
            continue
        tid = data.get("task_id", "")
        if not tid:
            continue
        all_ids.add(tid)
        if data.get("status") == "open":
            open_ids.add(tid)
            deps_by_open.append((tid, data.get("title", ""), parse_deps(data.get("depends_on", ""))))
    broken = [(tid, title, [d for d in deps if d not in all_ids])
              for tid, title, deps in deps_by_open if any(d not in all_ids for d in deps)]

    # Прохід 2: due-черга. Бита дата у frontmatter не валить команду — пропускаємо задачу
    # з due-черги (її ще видно в `list`), а не кидаємо трейсбек.
    due_rows, blocked = [], []
    for path in all_task_files():
        data, _, _, _ = load(path)
        if data.get("status") != "open" or not data.get("due"):
            continue
        due = parse_date_safe(data["due"])
        if due is None or due > boundary:
            continue
        tid = data.get("task_id", "")
        label = "OVERDUE" if due < today() else "DUE"
        row = f"{tid}\t{label}\t{data['due']}\t{data['project']}\t{data['title']}"
        unmet = [d for d in parse_deps(data.get("depends_on", "")) if d != tid and d in open_ids]
        if unmet:
            blocked.append((row, unmet))
        else:
            due_rows.append(row)

    if not (due_rows or blocked or broken):
        print("No due tasks.")
        return
    for row in due_rows:
        print(row)
    if blocked:
        print(f"\nBLOCKED — waiting on open dependencies ({len(blocked)}):")
        for row, unmet in blocked:
            print(f"  {row}")
            print(f"    waits on: {', '.join(unmet)}")
    if broken:
        print(f"\nBROKEN DEPS — id not found anywhere ({len(broken)}):")
        for tid, title, dangling in broken:
            print(f"  {tid}\t{title}\t-> unknown: {', '.join(dangling)}")


def cmd_show(args: argparse.Namespace) -> None:
    path = find_task(args.task_id)
    print(path.read_text(encoding="utf-8"), end="")
    print(f"PATH {path}")


def save_updated(path: Path, data: dict[str, str], context: str, completion: str, history: list[str]) -> None:
    data["updated"] = stamp()
    write_atomic(path, render(data, context, completion, history))


def cmd_done(args: argparse.Namespace) -> None:
    path = find_task(args.task_id)
    data, context, completion, history = load(path)
    if data.get("status") == "done":
        raise SystemExit(f"ERROR: already done: {data['task_id']}")
    data["status"] = "done"
    data["author"] = args.author or data.get("author", "unknown")
    note = f" · {args.note}" if args.note else ""
    history.append(f"- {stamp()} · done · {data['author']}{note}")
    month_dir = ARCHIVE / today().strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    save_updated(path, data, context, completion, history)
    target = month_dir / path.name
    shutil.move(str(path), target)
    sync_registry()
    print(f"DONE {data['task_id']}\nPATH {target}")


def cmd_reopen(args: argparse.Namespace) -> None:
    path = find_task(args.task_id)
    data, context, completion, history = load(path)
    if data.get("status") == "open":
        raise SystemExit(f"ERROR: already open: {data['task_id']}")
    data["status"] = "open"
    data["author"] = args.author or data.get("author", "unknown")
    history.append(f"- {stamp()} · reopened · {data['author']}")
    save_updated(path, data, context, completion, history)
    target = ACTIVE / path.name
    shutil.move(str(path), target)
    sync_registry()
    print(f"REOPENED {data['task_id']}\nPATH {target}")


def cmd_edit(args: argparse.Namespace) -> None:
    path = find_task(args.task_id)
    data, context, completion, history = load(path)
    changes = []
    for key in ("title", "project", "context", "completion"):
        value = getattr(args, key)
        if value is None:
            continue
        if key == "project":
            value = slugify(value, "general")
        if key == "context":
            context = value
        elif key == "completion":
            completion = value
        else:
            data[key] = value
        changes.append(key)
    for arg_key, data_key in (("due", "due"), ("remind", "remind_at")):
        value = getattr(args, arg_key)
        if value is not None:
            if value.lower() == "none":
                data[data_key] = ""
            elif data_key == "due":
                data[data_key] = parse_date(value).strftime(DATE_FMT)
            else:
                data[data_key] = parse_datetime(value).strftime(DATETIME_FMT)
            changes.append(data_key)
    dep_value = getattr(args, "depends_on", None)
    if dep_value is not None:
        data["depends_on"] = "" if dep_value.lower() == "none" else ",".join(parse_deps(dep_value))
        changes.append("depends_on")
    if not changes:
        raise SystemExit("ERROR: no changes supplied")
    data["author"] = args.author or data.get("author", "unknown")
    history.append(f"- {stamp()} · edited ({', '.join(changes)}) · {data['author']}")
    save_updated(path, data, context, completion, history)
    sync_registry()
    print(f"UPDATED {data['task_id']}\nPATH {path}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Persistent local Markdown task manager")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("add")
    p.add_argument("title")
    p.add_argument("--project", default="general")
    p.add_argument("--due", type=lambda v: parse_date(v).strftime(DATE_FMT))
    p.add_argument("--remind", type=lambda v: parse_datetime(v).strftime(DATETIME_FMT))
    p.add_argument("--context")
    p.add_argument("--source")
    p.add_argument("--completion")
    p.add_argument("--author")
    p.add_argument("--depends-on", dest="depends_on", help="task_id залежностей через кому")
    p.set_defaults(func=cmd_add)
    p = sub.add_parser("list")
    p.add_argument("--status", choices=("open", "done"), default="open")
    p.add_argument("--project")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("due")
    p.add_argument("--before")
    p.set_defaults(func=cmd_due)
    p = sub.add_parser("show")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("done")
    p.add_argument("task_id")
    p.add_argument("--note")
    p.add_argument("--author")
    p.set_defaults(func=cmd_done)
    p = sub.add_parser("reopen")
    p.add_argument("task_id")
    p.add_argument("--author")
    p.set_defaults(func=cmd_reopen)
    p = sub.add_parser("edit")
    p.add_argument("task_id")
    p.add_argument("--title")
    p.add_argument("--project")
    p.add_argument("--due")
    p.add_argument("--remind")
    p.add_argument("--context")
    p.add_argument("--completion")
    p.add_argument("--author")
    p.add_argument("--depends-on", dest="depends_on", help="task_id залежностей через кому ('none' очистити)")
    p.set_defaults(func=cmd_edit)
    return ap


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

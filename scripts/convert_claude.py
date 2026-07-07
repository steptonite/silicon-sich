#!/usr/bin/env python3
"""convert_claude.py — Claude-експорт (claude.ai data export) → lossless Markdown-архів.

Канон той самий, що convert_chatgpt/convert_gemini: нічого не втратити з тексту.
  • user/assistant текст — тіло нотатки (чисте, шукабельне)
  • thinking → згорнутий callout `> [!note]- 💭 …` (librarian strip_think_callouts
    вирізає його з індексу автоматично — той самий префікс, що в chatgpt-архіві)
  • tool_use / tool_result → згорнуті callout-и (кап 4000 симв.)
  • attachments.extracted_content → згорнутий callout 📎 (текст файлів ЗБЕРІГАЄМО)
  • files (самих байтів у експорті нема) → згадка за іменем
  • гілки: активний ланцюг від останнього листа = тіло; відрізані гілки —
    у згорнутому блоці «🌿 інша гілка» (lossless, але не заважає)
  • projects/*.json → projects/*.md; design_chats → design_chats/*.md;
    memories.json → memories.md (Claude-профіль користувача)

Ідемпотентний: hash у frontmatter, незмінені нотатки не перезаписуються.

  python3 convert_claude.py --src <export-dir> --out <archive-dir> [--limit N] [--user-label Ім'я]
"""
from __future__ import annotations
import argparse, glob, hashlib, json, re, sys
from pathlib import Path

ILLEGAL = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
WS = re.compile(r"\s+")
CAP = 4000  # кап на tool-вивід, як у chatgpt-конвертері

USER_LABEL = "Користувач"  # перевизначається з --user-label


def slugify(title: str, maxlen: int = 60) -> str:
    t = (title or "").strip() or "untitled"
    t = ILLEGAL.sub(" ", t)
    t = WS.sub(" ", t).strip().replace(" ", "_")
    return t[:maxlen].strip("_") or "untitled"


def d(ts: str | None) -> str:
    """ISO '2026-07-04T18:24:12.13Z' -> '2026-07-04'."""
    return (ts or "")[:10] or "0000-00-00"


def dt(ts: str | None) -> str:
    return (ts or "?")[:16].replace("T", " ")


def fold(title: str, body: str, kind: str = "note") -> str:
    lines = (body.strip() or " ").splitlines()
    quoted = "\n".join("> " + ln for ln in lines)
    return f"> [!{kind}]- {title}\n{quoted}"


def cap(s: str) -> str:
    s = s.strip()
    return s if len(s) <= CAP else s[:CAP] + "\n… [обрізано, повний вивід лише в експорті]"


def render_block(b: dict) -> str | None:
    t = b.get("type")
    if t == "text":
        return (b.get("text") or "").strip() or None
    if t == "thinking":
        body = (b.get("thinking") or "").strip()
        return fold("💭 міркування", body, "note") if body else None
    if t == "tool_use":
        name = b.get("name") or "tool"
        inp = b.get("input")
        body = json.dumps(inp, ensure_ascii=False, indent=1) if inp else ""
        return fold(f"⚙️ tool_use: {name}", f"```json\n{cap(body)}\n```", "example") if body else None
    if t == "tool_result":
        name = b.get("name") or "tool"
        c = b.get("content")
        if isinstance(c, list):
            body = "\n".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in c)
        elif isinstance(c, (dict,)):
            body = json.dumps(c, ensure_ascii=False)
        else:
            body = str(c or "")
        err = " ❌" if b.get("is_error") else ""
        body = body.strip()
        return fold(f"⚙️ tool_result: {name}{err}", cap(body), "example") if body else None
    # flag / token_budget / решта службового — пропускаємо
    return None


def render_message(m: dict) -> tuple[str | None, bool]:
    """-> (markdown, has_visible_text)"""
    parts, visible = [], False
    for b in m.get("content") or []:
        r = render_block(b)
        if r:
            parts.append(r)
            if b.get("type") == "text":
                visible = True
    # фолбек: старі повідомлення без content-блоків, але з text
    if not parts and (m.get("text") or "").strip():
        parts.append(m["text"].strip())
        visible = True
    for a in m.get("attachments") or []:
        ec = (a.get("extracted_content") or "").strip()
        name = a.get("file_name") or "file"
        if ec:
            parts.append(fold(f"📎 {name} (текст із вкладення)", cap(ec), "quote"))
        else:
            parts.append(f"`📎 вкладення: {name}`")
    for f in m.get("files") or []:
        parts.append(f"`🖼 вкладення (байтів нема в експорті): {f.get('file_name', '?')}`")
    return ("\n\n".join(parts).strip() or None), visible


def hdr_for(sender: str) -> str:
    return {"human": f"## 🧑 {USER_LABEL}", "assistant": "## 🤖 Claude"}.get(sender, f"## {sender}")


def active_chain(msgs: list) -> tuple[list, list]:
    """Активна гілка = ланцюг батьків від ОСТАННЬОГО повідомлення; решта = відрізані гілки."""
    if not msgs:
        return [], []
    by_id = {m["uuid"]: m for m in msgs}
    cur = msgs[-1]  # список відсортований за часом → останнє = актуальний лист
    chain, seen = [], set()
    while cur and cur["uuid"] not in seen:
        seen.add(cur["uuid"])
        chain.append(cur)
        cur = by_id.get(cur.get("parent_message_uuid"))
    chain.reverse()
    orphans = [m for m in msgs if m["uuid"] not in seen]
    return chain, orphans


def render_conversation(conv: dict) -> tuple[str, str, dict] | None:
    title = (conv.get("name") or "").strip() or "Без назви"
    msgs = conv.get("chat_messages") or []
    chain, orphans = active_chain(msgs)

    body_parts, msg_n = [], 0
    for m in chain:
        rendered, visible = render_message(m)
        if not rendered:
            continue
        body_parts.append(f"{hdr_for(m.get('sender'))}\n\n{rendered}")
        if visible:
            msg_n += 1
    if orphans:
        ob = []
        for m in orphans:
            rendered, _ = render_message(m)
            if rendered:
                who = USER_LABEL if m.get("sender") == "human" else "Claude"
                ob.append(fold(f"🌿 інша гілка · {who} · {dt(m.get('created_at'))}", rendered, "abstract"))
        body_parts.extend(ob)
    if msg_n == 0:
        return None

    body = "\n\n".join(body_parts).strip()
    h = hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]
    summary = (conv.get("summary") or "").strip()
    fm = {
        "title": title.replace('"', "'"),
        "created": d(conv.get("created_at")),
        "updated": d(conv.get("updated_at")),
        "conversation_id": conv.get("uuid") or "",
        "messages": msg_n,
        "source": "claude-export",
        "hash": h,
    }
    fm_lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, str):
            v = f'"{v}"' if (":" in v or "#" in v or v == "") else v
        fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")
    header = f"# {title}\n\n> [!info] {dt(conv.get('created_at'))} · {msg_n} повідомлень"
    if summary:
        header += "\n\n> [!summary]- анотація (Claude)\n" + "\n".join("> " + ln for ln in summary.splitlines())
    doc = "\n".join(fm_lines) + "\n\n" + header + "\n\n" + body + "\n"
    return doc, h, fm


def existing_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            for _ in range(30):
                ln = f.readline()
                if ln.startswith("hash:"):
                    return ln.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def write_if_changed(path: Path, doc: str, h: str) -> bool:
    if existing_hash(path) == h:
        return False
    path.write_text(doc, encoding="utf-8")
    return True


def convert_projects(src: Path, out: Path) -> int:
    pdir = out / "projects"
    pdir.mkdir(exist_ok=True)
    n = 0
    for f in sorted(glob.glob(str(src / "projects" / "*.json"))):
        p = json.load(open(f))
        if p.get("is_starter_project"):
            continue  # демо від Anthropic, не користувацьке
        title = (p.get("name") or "untitled").strip()
        parts = [f"# Проєкт: {title}", "",
                 f"> [!info] створено {dt(p.get('created_at'))} · оновлено {dt(p.get('updated_at'))}"]
        if (p.get("description") or "").strip():
            parts += ["", "## Інструкція проєкту (system prompt)", "", p["description"].strip()]
        if (p.get("prompt_template") or "").strip():
            parts += ["", "## Prompt template", "", p["prompt_template"].strip()]
        for doc_ in p.get("docs") or []:
            parts += ["", fold(f"📄 док: {doc_.get('filename', '?')}", cap(doc_.get("content") or ""), "quote")]
        body = "\n".join(parts) + "\n"
        h = hashlib.sha1(body.encode()).hexdigest()[:16]
        doc = f'---\ntitle: "{title}"\ncreated: {d(p.get("created_at"))}\nsource: claude-export-project\nhash: {h}\n---\n\n' + body
        if write_if_changed(pdir / f"{slugify(title)}_{p['uuid'][:8]}.md", doc, h):
            n += 1
    return n


def convert_design_chats(src: Path, out: Path) -> int:
    ddir = out / "design_chats"
    ddir.mkdir(exist_ok=True)
    n = 0
    for f in sorted(glob.glob(str(src / "design_chats" / "*.json"))):
        c = json.load(open(f))
        pname = (c.get("project") or {}).get("name", "")
        title = (c.get("title") or "Design chat").strip()
        if pname:
            title = f"{pname} — {title}"
        parts = [f"# {title}", "", f"> [!info] design-чат · {dt(c.get('created_at'))}"]
        for m in c.get("messages") or []:
            content = m.get("content")
            txt = content.get("content") if isinstance(content, dict) else content
            if not (txt and str(txt).strip()):
                continue
            hdr = f"## 🧑 {USER_LABEL}" if m.get("role") == "user" else "## 🤖 Claude"
            parts += ["", hdr, "", str(txt).strip()]
        body = "\n".join(parts) + "\n"
        h = hashlib.sha1(body.encode()).hexdigest()[:16]
        doc = f'---\ntitle: "{title}"\ncreated: {d(c.get("created_at"))}\nsource: claude-export-design\nhash: {h}\n---\n\n' + body
        if write_if_changed(ddir / f"{d(c.get('created_at'))}_{slugify(title)}_{c['uuid'][:8]}.md", doc, h):
            n += 1
    return n


def convert_memories(src: Path, out: Path) -> bool:
    f = src / "memories.json"
    if not f.exists():
        return False
    mm = json.load(open(f))
    # uuid → назва проєкту (для заголовків project_memories)
    pnames = {}
    for pf in glob.glob(str(src / "projects" / "*.json")):
        p = json.load(open(pf))
        pnames[p.get("uuid", "")] = p.get("name", "")
    parts = ["# Claude-пам'ять про користувача (memories.json)", "",
             "> [!info] Профіль, який Claude-хмара сама накопичила про користувача. Цінний сид для самарі."]
    for entry in mm:
        cm = (entry.get("conversations_memory") or "").strip()
        if cm:
            parts += ["", "## Пам'ять розмов", "", cm]
        pm = entry.get("project_memories") or {}
        items = pm.items() if isinstance(pm, dict) else ((None, x) for x in pm)
        for uuid_, body in items:
            body = str(body or "").strip()
            pname = pnames.get(uuid_) or uuid_ or "проєкт"
            if body:
                parts += ["", f"## Пам'ять проєкту: {pname}", "", body]
    body = "\n".join(parts) + "\n"
    h = hashlib.sha1(body.encode()).hexdigest()[:16]
    doc = f'---\ntitle: "Claude memories"\nsource: claude-export-memories\nhash: {h}\n---\n\n' + body
    return write_if_changed(out / "memories.md", doc, h)


def main():
    global USER_LABEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="тека розпакованого Claude-експорту")
    ap.add_argument("--out", required=True, help="тека архіву")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--user-label", default="Користувач", help="підпис людини в заголовках")
    a = ap.parse_args()
    USER_LABEL = a.user_label
    src, out = Path(a.src).expanduser(), Path(a.out).expanduser()
    (out / "chats").mkdir(parents=True, exist_ok=True)

    convs = json.load(open(src / "conversations.json"))
    convs.sort(key=lambda c: c.get("created_at") or "")
    if a.limit:
        convs = convs[: a.limit]
    print(f"[convert] розмов: {len(convs)}", file=sys.stderr)

    n_new = n_skip = n_empty = 0
    index, used = [], set()
    for conv in convs:
        r = render_conversation(conv)
        if not r:
            n_empty += 1
            continue
        doc, h, fm = r
        name = f"{fm['created']}_{slugify(fm['title'])}_{fm['conversation_id'][:8]}.md"
        base, i = name, 1
        while name in used:
            name = base[:-3] + f"_{i}.md"
            i += 1
        used.add(name)
        if write_if_changed(out / "chats" / name, doc, h):
            n_new += 1
        else:
            n_skip += 1
        index.append((fm["created"], fm["title"], "chats/" + name, fm["messages"]))

    n_proj = convert_projects(src, out)
    n_design = convert_design_chats(src, out)
    mem = convert_memories(src, out)

    index.sort(reverse=True)
    idx = ["# Claude архів", "",
           f"Всього розмов: **{len(index)}** · [[memories|Claude-пам'ять про користувача]] · "
           f"теки: projects/, design_chats/",
           "", "| Дата | Розмова | Повід. |", "|---|---|---|"]
    for created, title, rel, mn in index:
        idx.append(f"| {created} | [[{rel}\\|{title.replace('|', chr(92) + '|')}]] | {mn} |")
    (out / "_INDEX.md").write_text("\n".join(idx) + "\n", encoding="utf-8")

    print(f"[done] чатів нових/оновл.: {n_new} | без змін: {n_skip} | порожніх: {n_empty} | "
          f"проєктів: {n_proj} | design: {n_design} | memories: {'✚' if mem else '='} | → {out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()

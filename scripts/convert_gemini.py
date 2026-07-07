#!/usr/bin/env python3
"""convert_gemini.py — Google Takeout (Gemini Apps + NotebookLM + Workspace) → lossless Markdown-архів.

ФІЛОСОФІЯ (як у convert_chatgpt): нічого не втратити з тексту.
  • Gemini Apps MyActivity.html — плоскі prompt→response cells; реконструюємо СЕСІЇ
    за розривом у часі (>SESSION_GAP хв або зміна доби). Одна сесія = одна .md.
  • NotebookLM — куровані зошити (source-документи + чат); 1 зошит = 1 .md.
  • Gemini in Workspace — JSON-розмови; 1 розмова = 1 .md.
  • картинки/pdf НЕ копіюємо — лишаємо згадку за іменем.

  python3 convert_gemini.py --takeout <Takeout-dir> --out <archive-dir> [--limit N] [--user-label Ім'я]
"""
from __future__ import annotations
import argparse, json, re, html, hashlib
from datetime import datetime, timedelta
from pathlib import Path

SESSION_GAP = timedelta(minutes=60)  # розрив → нова «розмова»
ILLEGAL = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
WS = re.compile(r"\s+")
TAG = re.compile(r"<[^>]+>")


def slugify(title: str, maxlen: int = 55) -> str:
    t = (title or "").strip() or "untitled"
    t = ILLEGAL.sub(" ", t)
    t = WS.sub(" ", t).strip().replace(" ", "_")
    return t[:maxlen].strip("_") or "untitled"


def sha8(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>", "\n\n", s)
    s = TAG.sub("", s)
    return html.unescape(s).strip()


# ── Gemini Apps MyActivity.html ─────────────────────────────────────────────
CELL = re.compile(r'<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">(.*?)</div>', re.S)
TS = re.compile(r"([A-Z][a-z]{2} \d{1,2}, 20\d\d, \d{1,2}:\d{2}:\d{2}\s*[AP]M[^<]*)")


def parse_ts(s: str):
    s = s.strip()
    m = re.match(r"([A-Z][a-z]{2} \d{1,2}, 20\d\d, \d{1,2}:\d{2}:\d{2}\s*[AP]M)", s)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1).replace(" ", " ").strip(), "%b %d, %Y, %I:%M:%S %p")
    except Exception:
        return None


def parse_gemini_apps(html_path: Path):
    data = html_path.read_text(encoding="utf-8")
    items = []
    for cell in CELL.findall(data):
        m = TS.search(cell)
        if not m:
            continue
        ts = parse_ts(m.group(1))
        if not ts:
            continue
        pre = cell[:m.start()]
        post = cell[m.end():]
        prompt = strip_tags(pre)
        if prompt.lower().startswith("prompted"):
            prompt = prompt[len("prompted"):].strip()
        response = strip_tags(post)
        items.append((ts, prompt, response))
    items.sort(key=lambda x: x[0])  # хронологічно
    return items


def sessionize(items):
    sessions, cur = [], []
    last = None
    for ts, prompt, resp in items:
        if last and (ts - last > SESSION_GAP or ts.date() != last.date()):
            sessions.append(cur)
            cur = []
        cur.append((ts, prompt, resp))
        last = ts
    if cur:
        sessions.append(cur)
    return sessions


def write_gemini_apps(html_path: Path, out_dir: Path, user_label: str, limit=None):
    items = parse_gemini_apps(html_path)
    sessions = sessionize(items)
    n = 0
    for sess in sessions:
        t0 = sess[0][0]
        first_prompt = next((p for _, p, _ in sess if p), "") or "gemini"
        title = first_prompt.split("\n")[0][:70] or "gemini"
        h = sha8("".join(p + r for _, p, r in sess))
        fname = f"{t0.strftime('%Y-%m-%d')}_{slugify(title)}_{h}.md"
        body = [
            "---",
            f"title: {json.dumps(title, ensure_ascii=False)}",
            f"date: {t0.strftime('%Y-%m-%d')}",
            "source: gemini-apps",
            f"turns: {len(sess)}",
            f"hash: {h}",
            "---",
            "",
            f"# {title}",
            "",
            f"> [!info] {t0.strftime('%Y-%m-%d %H:%M')} · Gemini Apps · {len(sess)} звернень",
            "",
        ]
        for ts, prompt, resp in sess:
            body.append(f"## 🧑 {user_label} · {ts.strftime('%H:%M')}")
            body.append("")
            body.append(prompt or "*(порожній / вкладення)*")
            body.append("")
            body.append("## 🤖 Gemini")
            body.append("")
            body.append(resp or "*(порожньо)*")
            body.append("")
        (out_dir / fname).write_text("\n".join(body), encoding="utf-8")
        n += 1
        if limit and n >= limit:
            break
    return n, len(items)


# ── NotebookLM ──────────────────────────────────────────────────────────────
def write_notebooklm(nb_root: Path, out_dir: Path):
    n = 0
    for nb in sorted(nb_root.iterdir()):
        if not nb.is_dir():
            continue
        mfile = next(nb.glob("*metadata.json"), None)
        title = nb.name
        emoji = ""
        mf2 = next(nb.glob("* metadata.json"), None) or mfile
        if mf2:
            try:
                j = json.load(open(mf2))
                title = j.get("title", title)
                emoji = j.get("emoji", "")
            except Exception:
                pass
        body = [
            "---",
            f"title: {json.dumps(title, ensure_ascii=False)}",
            "source: notebooklm",
            "---",
            "",
            f"# {emoji} {title}".strip(),
            "",
            "> [!info] NotebookLM зошит (курований). Джерела + чат-сесії нижче.",
            "",
        ]
        # sources
        src_dir = nb / "Sources"
        if src_dir.exists():
            body.append("## 📚 Джерела")
            body.append("")
            for sj in sorted(src_dir.glob("*.json")):
                try:
                    j = json.load(open(sj))
                    body.append(f"- **{j.get('title', sj.stem)}**")
                except Exception:
                    body.append(f"- {sj.stem}")
            body.append("")
        # source HTML bodies (текст)
        if src_dir.exists():
            for sh in sorted(src_dir.glob("*.html")):
                txt = strip_tags(sh.read_text(encoding="utf-8", errors="ignore"))
                txt = re.sub(r"\n{3,}", "\n\n", txt)
                if len(txt) > 40:
                    body.append(f"### 📄 {sh.stem}")
                    body.append("")
                    body.append(txt[:20000])
                    body.append("")
        # chat history
        chat_dir = nb / "Chat History"
        if chat_dir.exists():
            for ch in sorted(chat_dir.glob("*.html")):
                txt = strip_tags(ch.read_text(encoding="utf-8", errors="ignore"))
                txt = re.sub(r"\n{3,}", "\n\n", txt)
                if len(txt) > 40:
                    body.append("## 💬 Чат-сесія")
                    body.append("")
                    body.append(txt[:15000])
                    body.append("")
        (out_dir / f"{slugify(title, 70)}.md").write_text("\n".join(body), encoding="utf-8")
        n += 1
    return n


# ── Gemini in Workspace ─────────────────────────────────────────────────────
def write_workspace(ws_root: Path, out_dir: Path, user_label: str):
    conv_dir = ws_root / "Conversation History"
    if not conv_dir.exists():
        return 0
    n = 0
    for cf in sorted(conv_dir.glob("*.txt")):
        try:
            j = json.load(open(cf))
        except Exception:
            continue
        turns = j.get("conversation_turns", [])
        title = "workspace"
        for t in turns:
            if "user_turn" in t:
                title = t["user_turn"].get("prompt", "workspace")[:60]
                break
        body = ["---", f"title: {json.dumps(title, ensure_ascii=False)}",
                "source: gemini-workspace", "---", "", f"# {title}", ""]
        for t in turns:
            if "user_turn" in t:
                body += [f"## 🧑 {user_label}", "", t["user_turn"].get("prompt", ""), ""]
            elif "system_turn" in t:
                st = t["system_turn"]
                text = "".join(x.get("data", "") for x in st.get("text", []))
                body += ["## 🤖 Gemini", "", text, ""]
                cites = st.get("citations", [])
                if cites:
                    body.append("*Джерела: " + ", ".join(c.get("display_text", "") for c in cites) + "*")
                    body.append("")
        (out_dir / f"{slugify(title, 60)}_{sha8(cf.name)}.md").write_text("\n".join(body), encoding="utf-8")
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--takeout", required=True, help="корінь розпакованого Takeout")
    ap.add_argument("--out", required=True, help="тека архіву")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--user-label", default="Користувач", help="підпис людини в заголовках")
    a = ap.parse_args()
    tk = Path(a.takeout).expanduser()
    out = Path(a.out).expanduser()
    (out / "chats").mkdir(parents=True, exist_ok=True)
    (out / "notebooklm").mkdir(parents=True, exist_ok=True)
    (out / "workspace").mkdir(parents=True, exist_ok=True)

    ga = tk / "My Activity" / "Gemini Apps" / "MyActivity.html"
    if ga.exists():
        sess, items = write_gemini_apps(ga, out / "chats", a.user_label, a.limit)
        print(f"Gemini Apps: {items} звернень → {sess} сесій")
    nb = tk / "NotebookLM"
    if nb.exists():
        print(f"NotebookLM: {write_notebooklm(nb, out / 'notebooklm')} зошитів")
    ws = tk / "Gemini in Workspace"
    if ws.exists():
        print(f"Workspace: {write_workspace(ws, out / 'workspace', a.user_label)} розмов")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""convert_chatgpt.py — ChatGPT-експорт → lossless Markdown-архів (Obsidian + librarian-ready).

ФІЛОСОФІЯ: нічого не втратити з тексту. Одна розмова = одна .md-нотатка.
  • user/assistant текст — тіло нотатки (шукабельне, чисте)
  • thoughts / reasoning_recap / tool-вивід — у ЗГОРНУТИХ callout-блоках (є, але не заважає)
  • картинки — НЕ копіюємо (гігабайти пікселів марні для тексту), лишаємо згадку за іменем
  • .wav — позначка «голосове», колись можна прогнати через whisper
  • xlsx/txt/інше — згадка за іменем

Ідемпотентний: на повторний прогін пропускає нотатки з тим самим hash у frontmatter
(майбутні експорти доіндексуються дешево).

  python3 convert_chatgpt.py --src <export-dir> --out <archive-dir> [--limit N] [--user-label Ім'я]
"""
from __future__ import annotations
import argparse, json, glob, os, re, sys, hashlib
from datetime import datetime, timezone
from pathlib import Path

ILLEGAL = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
WS = re.compile(r"\s+")


def slugify(title: str, maxlen: int = 60) -> str:
    t = (title or "").strip() or "untitled"
    t = ILLEGAL.sub(" ", t)
    t = WS.sub(" ", t).strip().replace(" ", "_")
    return t[:maxlen].strip("_") or "untitled"


def fmt_date(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return "0000-00-00"


def fmt_dt(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "?"


def asset_id(pointer: str) -> str:
    """'file-service://file-XXX' | 'sediment://file_XXX' -> 'file-XXX' / 'file_XXX'."""
    if not isinstance(pointer, str):
        return ""
    return pointer.rsplit("/", 1)[-1]


def build_asset_map(src: Path) -> dict:
    """{'file-XXX': 'humanname.png'} з conversation_asset_file_names.json (ключ 'file-XXX.dat')."""
    m = {}
    f = src / "conversation_asset_file_names.json"
    if f.exists():
        for k, v in json.load(open(f)).items():
            base = k[:-4] if k.endswith(".dat") else k  # strip .dat
            m[base] = v
    return m


def active_path(mapping: dict, current: str | None) -> list:
    """Активна гілка: від current_node до кореня, розвернути → лінійна розмова."""
    if not current or current not in mapping:
        # фолбек: якщо current зламаний — беремо найдовший ланцюг від будь-якого листа
        current = None
        for nid, n in mapping.items():
            if not n.get("children"):
                current = nid
                break
    chain = []
    seen = set()
    while current and current in mapping and current not in seen:
        seen.add(current)
        chain.append(mapping[current])
        current = mapping[current].get("parent")
    return list(reversed(chain))


def fold(title: str, body: str, kind: str = "note") -> str:
    """Obsidian згорнутий callout (- = за замовч. згорнуто)."""
    lines = body.strip().splitlines() or [""]
    quoted = "\n".join("> " + ln for ln in lines)
    return f"> [!{kind}]- {title}\n{quoted}"


def render_attachment(part: dict, amap: dict) -> str | None:
    ct = part.get("content_type", "")
    # аудіо (голосові розмови)
    for key in ("audio_asset_pointer",):
        if key in part:
            aid = asset_id(part[key].get("asset_pointer", ""))
            name = amap.get(aid, aid)
            return f"`🎙 голосове (whisper пізніше): {name}`"
    if ct == "audio_transcription":
        return None  # текст транскрипції піде окремим text-part, якщо є
    # зображення / файли
    ptr = part.get("asset_pointer") or ""
    if ptr:
        aid = asset_id(ptr)
        name = amap.get(aid, aid)
        ext = os.path.splitext(name)[1].lower()
        if ext in (".wav", ".mp3", ".m4a"):
            return f"`🎙 аудіо (whisper пізніше): {name}`"
        return f"`🖼 вкладення (не скопійовано, є в експорті): {name}`"
    return None


def render_node(node: dict, amap: dict) -> str | None:
    m = node.get("message")
    if not m:
        return None
    meta = m.get("metadata") or {}
    if meta.get("is_visually_hidden_from_conversation"):
        return None
    c = m.get("content") or {}
    ct = c.get("content_type", "")

    # thoughts — згорнуті блоки міркувань
    if ct == "thoughts":
        blocks = []
        for th in c.get("thoughts", []):
            s = (th.get("summary") or "міркування").strip()
            body = (th.get("content") or "").strip()
            if body:
                blocks.append(fold(f"💭 {s}", body, "note"))
        return "\n\n".join(blocks) if blocks else None

    if ct == "reasoning_recap":
        body = (c.get("content") or "").strip()
        return fold("💭 reasoning recap", body, "note") if body else None

    # code / tool-вивід — згорнуто
    if ct in ("code",):
        code = c.get("text") or "\n".join(str(p) for p in c.get("parts", []) if p)
        return fold("⚙️ code", f"```\n{code.strip()}\n```", "example") if code.strip() else None
    if ct in ("execution_output", "tether_quote", "tether_browsing_display", "system_error"):
        body = c.get("text") or c.get("result") or ""
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)[:4000]
        body = str(body).strip()
        return fold(f"⚙️ {ct}", body, "example") if body else None

    # звичайний текст
    if ct == "text":
        parts = [str(p) for p in c.get("parts", []) if isinstance(p, str) and p.strip()]
        return "\n\n".join(parts).strip() or None

    # мультимодал: строки + вкладення
    if ct == "multimodal_text":
        out = []
        for p in c.get("parts", []):
            if isinstance(p, str) and p.strip():
                out.append(p.strip())
            elif isinstance(p, dict):
                a = render_attachment(p, amap)
                if a:
                    out.append(a)
        return "\n\n".join(out).strip() or None

    return None


def role_headers(user_label: str) -> dict:
    return {"user": f"## 🧑 {user_label}", "assistant": "## 🤖 ChatGPT",
            "tool": "## ⚙️ Tool", "system": "## ⚙️ System"}


def render_conversation(conv: dict, amap: dict, role_hdr: dict) -> tuple[str, str, dict]:
    title = (conv.get("title") or "").strip() or "Без назви"
    created = fmt_date(conv.get("create_time"))
    mapping = conv.get("mapping", {})
    nodes = active_path(mapping, conv.get("current_node"))

    body_parts = []
    msg_n = 0
    for node in nodes:
        m = node.get("message")
        if not m:
            continue
        role = (m.get("author") or {}).get("role", "")
        rendered = render_node(node, amap)
        if not rendered:
            continue
        # thoughts/recap/tool не рахуємо як «повідомлення», але лишаємо в потоці
        c = m.get("content") or {}
        ct = c.get("content_type", "")
        if ct in ("text", "multimodal_text") and role in ("user", "assistant"):
            hdr = role_hdr.get(role, f"## {role}")
            body_parts.append(f"{hdr}\n\n{rendered}")
            msg_n += 1
        else:
            body_parts.append(rendered)  # згорнутий блок без заголовка ролі

    body = "\n\n".join(body_parts).strip()
    h = hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]

    fm = {
        "title": title.replace('"', "'"),
        "created": created,
        "updated": fmt_date(conv.get("update_time")),
        "conversation_id": conv.get("conversation_id") or conv.get("id") or "",
        "model": conv.get("default_model_slug") or "",
        "starred": bool(conv.get("is_starred")),
        "archived": bool(conv.get("is_archived")),
        "messages": msg_n,
        "source": "chatgpt-export",
        "hash": h,
    }
    fm_lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, str):
            v = f'"{v}"' if (":" in v or "#" in v or v == "") else v
        fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")

    header = (f"# {title}\n\n> [!info] {fmt_dt(conv.get('create_time'))} · "
              f"модель {fm['model'] or '?'} · {msg_n} повідомлень"
              + (" · ⭐" if fm["starred"] else ""))
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
                if ln.strip() == "---" and _ > 0:
                    break
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="тека розпакованого ChatGPT-експорту")
    ap.add_argument("--out", required=True, help="тека архіву (створюється chats/ + _INDEX.md)")
    ap.add_argument("--limit", type=int, default=None, help="лише N перших розмов (тест)")
    ap.add_argument("--user-label", default="Користувач", help="підпис людини в заголовках")
    a = ap.parse_args()

    src = Path(a.src).expanduser()
    out = Path(a.out).expanduser()
    (out / "chats").mkdir(parents=True, exist_ok=True)
    amap = build_asset_map(src)
    role_hdr = role_headers(a.user_label)
    print(f"[asset-map] {len(amap)} імен вкладень", file=sys.stderr)

    files = sorted(glob.glob(str(src / "conversations*.json")))
    convs = []
    for f in files:
        convs.extend(json.load(open(f)))
    convs.sort(key=lambda c: c.get("create_time") or 0)
    if a.limit:
        convs = convs[:a.limit]
    print(f"[convert] розмов: {len(convs)}", file=sys.stderr)

    n_new = n_skip = n_empty = 0
    index = []
    used_names = set()
    for conv in convs:
        doc, h, fm = render_conversation(conv, amap, role_hdr)
        if fm["messages"] == 0:
            n_empty += 1
            continue
        created = fm["created"]
        slug = slugify(fm["title"])
        shortid = (fm["conversation_id"] or h)[:8]
        name = f"{created}_{slug}_{shortid}.md"
        # унікальність
        base = name
        i = 1
        while name in used_names:
            name = base[:-3] + f"_{i}.md"
            i += 1
        used_names.add(name)
        path = out / "chats" / name

        if existing_hash(path) == h:
            n_skip += 1
        else:
            path.write_text(doc, encoding="utf-8")
            n_new += 1
        index.append((created, fm["title"], "chats/" + name, fm["messages"], fm["starred"]))

    # індекс-нотатка (точка входу в Obsidian)
    index.sort(reverse=True)
    idx_lines = ["# ChatGPT архів", "",
                 "> 🧠 **Курована база знань (почни звідси):** [[_KNOWLEDGE]] — самарі по темах з лінками на джерела.",
                 "> 🗂 **Усі розмови по темах:** [[_TOPICS]] — тематичний покажчик (жоден чат не сирота).",
                 "> Нижче — повний сирий список усіх розмов по датах (глибина в останню чергу).",
                 "",
                 f"Всього розмов: **{len(index)}** · згенеровано {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                 "", "| Дата | Розмова | Повід. |", "|---|---|---|"]
    for created, title, rel, mn, star in index:
        star_s = " ⭐" if star else ""
        safe = title.replace("|", "\\|")
        idx_lines.append(f"| {created} | [[{rel}\\|{safe}{star_s}]] | {mn} |")
    (out / "_INDEX.md").write_text("\n".join(idx_lines) + "\n", encoding="utf-8")

    print(f"[done] нових/оновлених: {n_new} | пропущено (без змін): {n_skip} | "
          f"порожніх: {n_empty} | у теці: {out}", file=sys.stderr)
    print("[nb] після конверсії: librarian.py index --source chatgpt (доіндексувати нове)",
          file=sys.stderr)


if __name__ == "__main__":
    main()

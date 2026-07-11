#!/usr/bin/env python3
"""librarian.py — семантичний індекс над memory-графом, vault-нотами і чат-архівами.

ІДЕЯ: контекст живе на диску (Obsidian-граф memory-теки + архіви чатів), а не в
крихкому вікні що компактиться. Цей тул кладе все у векторний індекс і дістає лише
потрібний шматок на вимогу → не впираємось у контекст, економимо токени на ПРИГАДУВАННІ.
Obsidian — окремо, лише ВІЗУАЛІЗАТОР графа для людини; цей індекс — пошук для моделі.

ДЖЕРЕЛА (колонка source; шляхи — з config.toml, див. sb_config.py):
  memory      — memory-граф (одна нота = один факт; MEMORY.md НЕ заганяється)
  chatgpt     — конвертований ChatGPT-архів (chats/*.md)
  knowledge   — куровані самарі (ланцюг знань — ранжуються ВИЩЕ сирих чатів)
  gemini      — Gemini/Takeout архів
  claude      — Claude-хмара експорт
  inbox       — сирі надиктовки користувача
  tasks       — підтверджені дії (active + archive)
  claude-code — сирі локальні сесії Claude Code
  codex       — сирі локальні сесії Codex
  transcript  — транскрипти сесій Claude Code (*.jsonl)
  skills      — SKILL.md локальних скілів («який скіл під задачу»)

EMBED-РУШІЙ: bge-m3 (1024-вим), два РІВНОЦІННІ варіанти (див. docs/04-semantics.md):
  A) OpenRouter — без локальних установок: openrouter_enabled=true у config.toml
     + ключ (env OPENROUTER_API_KEY або env_file). Ціна копійчана.
  B) локальний Ollama — $0, приватно; M-серія Mac 8ГБ тягне.
  Дефолт --backend auto: Ollama якщо живий, інакше OpenRouter (якщо ввімкнено).
  Та сама модель обидва боки → вектори сумісні, переіндексація не потрібна.

ЮЗАННЯ (через venv-python):
  python librarian.py index --source memory
  python librarian.py index --source all
  python librarian.py search "що ми вирішили про озвучку" -k 8
  python librarian.py search "тема" --source memory
  python librarian.py stats
"""
import os, sys, json, time, re, argparse, hashlib, urllib.request, sqlite3
from pathlib import Path

import sqlite_vec

from sb_config import CFG, P

DB_PATH = P(CFG["index"]["db_path"])
ENV_FILE = P(CFG["embed"].get("env_file", "~/.config/second-brain/.env"))

MEMORY_DIR = P(CFG["vault"]["memory"])
INBOX_DIR = P(CFG["vault"]["inbox"])
TASKS_DIR = P(CFG["vault"].get("tasks", "~/SecondBrain/tasks"))
CHATGPT_DIR = P(CFG["archives"]["chatgpt"]) / "chats"
KNOWLEDGE_DIR = P(CFG["archives"]["knowledge"])
GEMINI_DIR = P(CFG["archives"]["gemini"])
CLAUDE_DIR = P(CFG["archives"]["claude"])
CLAUDE_CODE_DIR = P(CFG["archives"].get("claude_code", "~/code/claude-code-archive"))
CODEX_DIR = P(CFG["archives"].get("codex", "~/code/codex-archive"))
PROJECTS_DIR = P(CFG["claude_code"]["projects_dir"])
SKILLS_DIR = P(CFG["claude_code"]["skills_dir"])

DIM = 1024
OR_EMBED_URL = "https://openrouter.ai/api/v1/embeddings"
OR_MODEL = CFG["embed"].get("openrouter_model", "baai/bge-m3")
OR_ENABLED = bool(CFG["embed"].get("openrouter_enabled", False))
OLLAMA_BASE = CFG["embed"].get("ollama_url", "http://localhost:11434").rstrip("/")
OLLAMA_URL = OLLAMA_BASE + "/api/embed"
OLLAMA_MODEL = CFG["embed"].get("ollama_model", "bge-m3")
BATCH = 48
TIMEOUT = 180
PRICE_PER_MTOK = 0.01  # bge-m3 на OpenRouter

_usage_tokens = 0  # сумарні токени embed за прогін (для звіту вартості)

# Ранжування ланцюга знань: курований шар (самарі/memory) отримує знижку до відстані,
# щоб спливати ПЕРШИМ над дослівними сирими чатами. Множник <1 = ближче = вище.
# Без цього десятки тисяч сирих чанків завжди перекрикують жменю knowledge-чанків —
# ланцюг знань був би декларацією, а не поведінкою.
SOURCE_WEIGHT = {"knowledge": 0.82, "memory": 0.85, "tasks": 0.92,
                 "chatgpt": 1.0, "gemini": 1.0, "claude": 1.0, "transcript": 1.05,
                 "inbox": 1.0, "claude-code": 1.0, "codex": 1.0}
# Сирі, неверифіковані шари — виводимо з банером недовіри (у самарі є ⚠️, у сирому нема).
UNVERIFIED_SRC = {"chatgpt": "⚠️ сирий чат ChatGPT — НЕ верифіковано (модель могла помилятись)",
                  "gemini": "⚠️ сира розмова з Gemini — НЕ верифіковано (модель могла помилятись)",
                  "claude": "⚠️ сирий чат Claude — не курований (сире ≠ канон)",
                  "inbox": "⚠️ сира надиктовка користувача з inbox — ще не розфасована",
                  "tasks": "📋 локальна task-система — стан дії дивись у frontmatter",
                  "claude-code": "⚠️ сира Claude Code-сесія — не курована",
                  "codex": "⚠️ сира Codex-сесія — не курована",
                  "transcript": "⚠️ сирий транскрипт — не куроване знання"}
# NotebookLM-зошити всередині gemini-архіву — куровані (модель сама зводить джерела),
# золото як knowledge, тому окрема вага і БЕЗ банера недовіри. Розрізняємо по підшляху ref.
NOTEBOOKLM_WEIGHT = 0.85


def eff_weight(src: str, ref: str) -> float:
    if src == "gemini" and "/notebooklm/" in ref:
        return NOTEBOOKLM_WEIGHT
    return SOURCE_WEIGHT.get(src, 1.0)


def eff_warn(src: str, ref: str) -> str | None:
    if src == "gemini" and "/notebooklm/" in ref:
        return None  # курований зошит — не сира розмова
    return UNVERIFIED_SRC.get(src)


# ─────────────────────────── ключ ───────────────────────────
def load_key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if k:
        return k
    if ENV_FILE.exists():
        txt = ENV_FILE.read_text(encoding="utf-8")
        for line in txt.splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
        m = re.search(r"sk-or-v1-[A-Za-z0-9]+", txt)  # стійкість до кривого формату .env
        if m:
            return m.group(0)
    sys.exit(f"ERROR: нема OPENROUTER_API_KEY (env або {ENV_FILE})")


# ─────────────────────────── embed ───────────────────────────
def embed_openrouter(texts: list[str]) -> list[list[float]]:
    global _usage_tokens
    req = urllib.request.Request(
        OR_EMBED_URL,
        data=json.dumps({"model": OR_MODEL, "input": texts}).encode("utf-8"),
        headers={"Authorization": f"Bearer {load_key()}", "Content-Type": "application/json",
                 "X-Title": "second-brain-librarian"},
        method="POST",
    )
    last = None
    for attempt in range(5):  # ретрай на транзиентних збоях (429/5xx/мережа)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                resp = json.loads(r.read().decode("utf-8"))
            if "data" not in resp:  # прилетів об'єкт помилки замість embeddings
                last = f"OR без 'data': {json.dumps(resp, ensure_ascii=False)[:200]}"
                time.sleep(2 * (attempt + 1))
                continue
            _usage_tokens += resp.get("usage", {}).get("prompt_tokens", 0) \
                or resp.get("usage", {}).get("total_tokens", 0)
            return [d["embedding"] for d in sorted(resp["data"], key=lambda d: d["index"])]
        except Exception as e:  # HTTPError/URLError/timeout → бекоф і повтор
            last = f"{type(e).__name__}: {e}"
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"embed_openrouter впав після 5 спроб — {last}")


def embed_ollama(texts: list[str]) -> list[list[float]]:
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps({"model": OLLAMA_MODEL, "input": texts}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return resp["embeddings"]


def ollama_alive() -> bool:
    try:
        urllib.request.urlopen(OLLAMA_BASE + "/api/tags", timeout=3)
        return True
    except Exception:
        return False


def resolve_engine(backend: str) -> str:
    """Який рушій РЕАЛЬНО відпрацює зараз (для чесного announce)."""
    if backend in ("openrouter", "ollama"):
        return backend
    return "ollama" if ollama_alive() else "openrouter"


def embed(texts: list[str], backend: str) -> list[list[float]]:
    if backend == "ollama":
        return embed_ollama(texts)
    if backend == "auto":
        if ollama_alive():
            try:
                return embed_ollama(texts)
            except Exception as e:
                print(f"  [warn] ollama впав ({e})", file=sys.stderr)
        if not OR_ENABLED:
            sys.exit("ERROR: Ollama недоступний, а OpenRouter вимкнено "
                     "(embed.openrouter_enabled=false у config.toml). Два виходи: "
                     "підняти Ollama (`ollama serve`) АБО ввімкнути openrouter_enabled=true + ключ.")
        print("  [warn] фолбек на OpenRouter", file=sys.stderr)
        return embed_openrouter(texts)
    return embed_openrouter(texts)


# ─────────────────────────── db ───────────────────────────
def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.enable_load_extension(False)
    # кілька писців (PreCompact-хук, ручні виклики) → WAL,
    # інакше рано чи пізно "database is locked"
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, source TEXT, ref TEXT, chunk_idx INTEGER, text TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_ref ON chunks(ref)")
    c.execute("CREATE TABLE IF NOT EXISTS files(ref TEXT PRIMARY KEY, source TEXT, sha TEXT, n_chunks INTEGER, indexed_at REAL)")
    c.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS vchunks USING vec0(embedding float[{DIM}])")
    return c


# ─────────────────────────── чанкінг ───────────────────────────
def chunk_text(text: str, target: int = 2000, overlap: int = 200) -> list[str]:
    paras = re.split(r"\n\s*\n", text)
    chunks, cur = [], ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if len(cur) + len(p) + 2 <= target:
            cur = (cur + "\n\n" + p) if cur else p
        else:
            if cur:
                chunks.append(cur)
                cur = ""
            if len(p) <= target:
                cur = p
            else:
                for i in range(0, len(p), target - overlap):
                    chunks.append(p[i:i + target])
    if cur:
        chunks.append(cur)
    return [c for c in (x.strip() for x in chunks) if c]


# ─────────────────────────── джерела ───────────────────────────
def gather_memory() -> list[tuple[str, str]]:
    out = []
    if MEMORY_DIR.exists():
        for fp in sorted(MEMORY_DIR.glob("*.md")):
            if fp.name == "MEMORY.md":  # індекс, не заганяємо
                continue
            out.append((str(fp), fp.read_text(encoding="utf-8")))
    return out


def _extract_jsonl(fp: Path) -> str:
    """Витягти зв'язний текст user/assistant-ходів із транскрипту, відкинувши tool-шум."""
    turns = []
    for line in fp.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        msg = obj.get("message") or obj
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            text = "\n".join(p for p in parts if p)
        text = text.strip()
        if text:
            turns.append(f"[{role}] {text}")
    return "\n\n".join(turns)


def gather_transcripts() -> list[tuple[str, str]]:
    out = []
    if PROJECTS_DIR.exists():
        for fp in sorted(PROJECTS_DIR.rglob("*.jsonl")):
            try:
                txt = _extract_jsonl(fp)
            except Exception:
                txt = ""
            if txt.strip():
                out.append((str(fp), txt))
    return out


def strip_think_callouts(text: str) -> str:
    """Викинути внутрішні роздуми моделі (Obsidian-callout `> [!note]- 💭 …`) перед індексацією.
    Це найменш надійний шар (думки моделі, часто хибні) — не має конкурувати за топ видачі.
    Прибираємо суцільний блок цитати ('>'-рядки), що починається з рядка-заголовка з 💭."""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        # заголовок callout-думки: '> [!...]- 💭 ...' (з опційним відступом)
        if re.match(r"^\s*>\s*\[!\w+\][+-]?\s*💭", ln):
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                i += 1
            continue
        out.append(ln)
        i += 1
    return "\n".join(out)


def gather_chatgpt() -> list[tuple[str, str]]:
    """ChatGPT-архів: по одному .md на розмову. 💭-think-блоки вирізаємо перед
    індексацією (див. strip_think_callouts). Стабільний ref=шлях → дешева доіндексація."""
    out = []
    if CHATGPT_DIR.exists():
        for fp in sorted(CHATGPT_DIR.glob("*.md")):
            try:
                out.append((str(fp), strip_think_callouts(fp.read_text(encoding="utf-8"))))
            except Exception:
                pass
    return out


def gather_knowledge() -> list[tuple[str, str]]:
    """Куровані самарі (ланцюг знань). Окреме джерело — щоб доіндексовувати
    дешево, не чіпаючи тисячі чанків сирих чатів."""
    out = []
    if KNOWLEDGE_DIR.exists():
        for fp in sorted(KNOWLEDGE_DIR.glob("*.md")):
            try:
                out.append((str(fp), fp.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out


def gather_gemini() -> list[tuple[str, str]]:
    """Gemini/Google Takeout архів: chats (сесії з MyActivity), notebooklm (куровані
    зошити), workspace (розмови). Стабільний ref=шлях → дешева доіндексація."""
    out = []
    if GEMINI_DIR.exists():
        for fp in sorted(GEMINI_DIR.rglob("*.md")):
            try:
                out.append((str(fp), fp.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out


def gather_claude() -> list[tuple[str, str]]:
    """Claude-хмара експорт: chats + projects + design_chats + memories.md.
    Стабільний ref=шлях → дешева доіндексація майбутніх експортів."""
    out = []
    if CLAUDE_DIR.exists():
        for fp in sorted(CLAUDE_DIR.rglob("*.md")):
            try:
                # 💭-callout-и (thinking) вирізаємо з індексу, як у chatgpt
                out.append((str(fp), strip_think_callouts(fp.read_text(encoding="utf-8"))))
            except Exception:
                pass
    return out


def gather_inbox() -> list[tuple[str, str]]:
    """Сирі надиктовки користувача (inbox). Системний _INBOX.md не заганяємо.
    Оброблені (status: processed) лишаються як якорі-першоджерела — теж індексуємо,
    бо їх все одно шукаємо; банер сирого попереджає, що це не курований канон."""
    out = []
    if INBOX_DIR.exists():
        for fp in sorted(INBOX_DIR.glob("*.md")):
            if fp.name == "_INBOX.md":  # системна нота-інструкція, не контент
                continue
            try:
                out.append((str(fp), fp.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out


def gather_md_tree(root: Path) -> list[tuple[str, str]]:
    out = []
    if root.exists():
        for fp in sorted(root.rglob("*.md")):
            try:
                out.append((str(fp), fp.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out


def gather_tasks() -> list[tuple[str, str]]:
    """Підтверджені дії: active і незмінний архів історії."""
    return gather_md_tree(TASKS_DIR)


def gather_claude_code() -> list[tuple[str, str]]:
    return gather_md_tree(CLAUDE_CODE_DIR / "md")


def gather_codex() -> list[tuple[str, str]]:
    return gather_md_tree(CODEX_DIR / "md")


def gather_skills() -> list[tuple[str, str]]:
    """Скіли (skills_dir/*/SKILL.md): семантичний пошук «який скіл під цю задачу?».
    Індексуємо лише шапку (frontmatter+перші ~2500 симв) — тригер-опис, не все тіло."""
    out = []
    if SKILLS_DIR.exists():
        for fp in sorted(SKILLS_DIR.glob("*/SKILL.md")):
            try:
                out.append((str(fp), fp.read_text(encoding="utf-8")[:2500]))
            except Exception:
                pass
    return out


GATHER = {"memory": gather_memory, "transcript": gather_transcripts,
          "chatgpt": gather_chatgpt, "knowledge": gather_knowledge, "gemini": gather_gemini,
          "claude": gather_claude, "inbox": gather_inbox, "tasks": gather_tasks,
          "claude-code": gather_claude_code, "codex": gather_codex,
          "skills": gather_skills}


# ─────────────────────────── index ───────────────────────────
def index_source(c: sqlite3.Connection, source: str, backend: str, limit: int | None):
    docs = GATHER[source]()
    if limit:
        docs = docs[:limit]
    print(f"[{source}] файлів: {len(docs)}", file=sys.stderr)
    if resolve_engine(backend) == "openrouter":
        print(f"[OpenRouter] звертаюсь до ключа: embeddings {OR_MODEL} (індексація {source})", file=sys.stderr)
    else:
        print(f"[Ollama] локальний embed {OLLAMA_MODEL} (індексація {source}, $0)", file=sys.stderr)

    n_new = n_skip = n_chunks = 0
    for ref, text in docs:
        sha = hashlib.sha1(text.encode("utf-8")).hexdigest()
        row = c.execute("SELECT sha FROM files WHERE ref=?", (ref,)).fetchone()
        if row and row[0] == sha:
            n_skip += 1
            continue
        chunks = chunk_text(text)
        # файли ростуть дописуванням (транскрипти — завжди) → чанки-префікс
        # збігаються зі старими; переembed'имо лише хвіст від точки розбіжності
        old = c.execute("SELECT id, text FROM chunks WHERE ref=? ORDER BY chunk_idx",
                        (ref,)).fetchall()
        keep = 0
        while keep < len(old) and keep < len(chunks) and old[keep][1] == chunks[keep]:
            keep += 1
        stale = [r[0] for r in old[keep:]]
        if stale:
            c.executemany("DELETE FROM vchunks WHERE rowid=?", [(i,) for i in stale])
            c.executemany("DELETE FROM chunks WHERE id=?", [(i,) for i in stale])
        tail = chunks[keep:]
        for bi in range(0, len(tail), BATCH):
            batch = tail[bi:bi + BATCH]
            vecs = embed(batch, backend)
            for j, (ch, v) in enumerate(zip(batch, vecs)):
                cur = c.execute(
                    "INSERT INTO chunks(source, ref, chunk_idx, text) VALUES (?,?,?,?)",
                    (source, ref, keep + bi + j, ch))
                rid = cur.lastrowid
                c.execute("INSERT INTO vchunks(rowid, embedding) VALUES (?, ?)",
                          (rid, sqlite_vec.serialize_float32(v)))
            n_chunks += len(batch)
        c.execute("INSERT OR REPLACE INTO files(ref, source, sha, n_chunks, indexed_at) VALUES (?,?,?,?,?)",
                  (ref, source, sha, len(chunks), time.time()))
        c.commit()
        n_new += 1
        print(f"  + {Path(ref).name}  ({len(chunks)} чанків)", file=sys.stderr)

    print(f"[{source}] нових/змінених: {n_new}, пропущено (без змін): {n_skip}, чанків додано: {n_chunks}",
          file=sys.stderr)


def cmd_index(sources: list[str], backend: str, limit: int | None):
    c = connect()
    t0 = time.time()
    for s in sources:
        index_source(c, s, backend, limit)
    c.close()
    dt = time.time() - t0
    if _usage_tokens:
        cost = _usage_tokens / 1e6 * PRICE_PER_MTOK
        print(f"\nГотово за {dt:.0f}с. Embed-токенів: {_usage_tokens:,} ≈ ${cost:.4f}", file=sys.stderr)
    else:
        print(f"\nГотово за {dt:.0f}с (локальний embed, $0).", file=sys.stderr)


# ─────────────────────────── search ───────────────────────────
def cmd_search(query: str, source: str | None, k: int, backend: str):
    c = connect()
    if resolve_engine(backend) == "openrouter":
        print(f"[OpenRouter] звертаюсь до ключа: embeddings {OR_MODEL} (пошук-запит)", file=sys.stderr)
    else:
        print(f"[Ollama] локальний embed {OLLAMA_MODEL} (пошук-запит, $0)", file=sys.stderr)
    qv = embed([query], backend)[0]
    # Завжди беремо широкий кандидат-сет: (а) фільтр по source пост-KNN, мала підмножина
    # інакше не спливає; (б) навіть без фільтра курований шар треба перевзважити (див.
    # SOURCE_WEIGHT) — у сирий топ-k він міг не потрапити взагалі.
    fetch = 2000 if source else max(k * 40, 400)
    rows = c.execute(
        "SELECT v.rowid, v.distance FROM vchunks v WHERE v.embedding MATCH ? AND k=? ORDER BY v.distance",
        (sqlite_vec.serialize_float32(qv), fetch)).fetchall()
    cand = []
    for rid, dist in rows:
        meta = c.execute("SELECT source, ref, chunk_idx, text FROM chunks WHERE id=?", (rid,)).fetchone()
        if not meta:
            continue
        src, ref, idx, text = meta
        if source and src != source:
            continue
        adj = dist * eff_weight(src, ref)  # перевзважений ранг ланцюга знань
        cand.append((adj, dist, src, ref, idx, text))
    cand.sort(key=lambda r: r[0])
    results = cand[:k]
    c.close()
    if not results:
        print("Нічого не знайдено.")
        return
    for adj, dist, src, ref, idx, text in results:
        snippet = text if len(text) <= 600 else text[:600] + "…"
        warn = eff_warn(src, ref)
        nm = Path(ref).name
        if nm == "SKILL.md":  # ім'я скіла = тека, не файл
            nm = f"{Path(ref).parent.name}/SKILL.md"
        head = f"\n── [{src}] {nm} #{idx}  (dist {dist:.3f}) ──"
        if warn:
            head += f"\n   {warn}"
        print(f"{head}\n{snippet}")


def cmd_stats():
    c = connect()
    print("Індекс:", DB_PATH)
    for src, n in c.execute("SELECT source, COUNT(*) FROM chunks GROUP BY source").fetchall():
        print(f"  {src:11s} {n:>7} чанків")
    total = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    files = c.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    print(f"  {'РАЗОМ':11s} {total:>7} чанків з {files} файлів")
    c.close()
    if DB_PATH.exists():
        print(f"Розмір .db: {DB_PATH.stat().st_size/1e6:.1f} МБ")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Семантичний бібліотекар (sqlite-vec + bge-m3)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("index")
    pi.add_argument("--source", required=True,
                    choices=["memory", "transcripts", "chatgpt", "knowledge", "gemini", "claude", "inbox", "tasks", "claude-code", "codex", "skills", "all"])
    pi.add_argument("--backend", default="auto", choices=["openrouter", "ollama", "auto"])
    pi.add_argument("--limit", type=int, default=None, help="обмежити к-сть файлів (для тесту)")
    ps = sub.add_parser("search")
    ps.add_argument("query")
    ps.add_argument("--source", default=None,
                    choices=["memory", "transcript", "chatgpt", "knowledge", "gemini", "claude", "inbox", "tasks", "claude-code", "codex", "skills"])
    ps.add_argument("-k", type=int, default=8)
    ps.add_argument("--backend", default="auto", choices=["openrouter", "ollama", "auto"])
    ps.add_argument("--b64", action="store_true", help="query передано у base64 (shell-safe)")
    sub.add_parser("stats")
    a = ap.parse_args()

    if a.cmd == "index":
        srcs = list(GATHER) if a.source == "all" else \
               ["transcript" if a.source == "transcripts" else a.source]
        cmd_index(srcs, a.backend, a.limit)
    elif a.cmd == "search":
        q = a.query
        if a.b64:
            import base64
            q = base64.b64decode(q.encode("ascii")).decode("utf-8")
        cmd_search(q, a.source, a.k, a.backend)
    elif a.cmd == "stats":
        cmd_stats()

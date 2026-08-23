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
import os, sys, json, time, re, argparse, hashlib, urllib.request, sqlite3, math
from collections import Counter
from datetime import date, datetime
from pathlib import Path

try:
    import sqlite_vec
except ModuleNotFoundError:  # людині — речення, не стектрейс
    sys.exit(
        "🔴 Немає бібліотеки sqlite-vec — без неї семантичний пошук не працює.\n"
        "   Полагодити однією командою:  bash doctor.sh --fix\n"
        "   (вручну: python3 -m pip install -r requirements.txt)"
    )

import embed_journal
import cost_gate

from sb_config import CFG, P

DB_PATH = Path(os.environ.get("LIBRARIAN_DB_PATH", P(CFG["index"]["db_path"]))).expanduser()
ENV_FILE = P(CFG["embed"].get("env_file", "~/.config/second-brain/.env"))

MEMORY_DIR = P(CFG["vault"]["memory"])
VAULT_DIR = P(CFG["vault"]["root"])
INBOX_DIR = P(CFG["vault"]["inbox"])
TASKS_DIR = P(CFG["vault"].get("tasks", "~/SecondBrain/tasks"))
EXTERNAL_DIR = P(CFG["vault"].get("external", "~/SecondBrain/external"))
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
# 🔴 22.08.2026, перша платна установка. «Ключ дозволений» і «дозволено мовчки
# витрачати гроші» — це були ОДНЕ поле. Людина вмикала openrouter_enabled, щоб
# мати запасний варіант, а отримувала автоматичний вихід у мережу щоразу, коли
# Ollama просто не піднялась. Для кита, який продається як «$0 і приватно»,
# дефолт мусить бути протилежний: мовчки в мережу не йдемо.
OR_FALLBACK = bool(CFG["embed"].get("openrouter_fallback", False))
OLLAMA_BASE = CFG["embed"].get("ollama_url", "http://localhost:11434").rstrip("/")
OLLAMA_URL = OLLAMA_BASE + "/api/embed"
OLLAMA_MODEL = CFG["embed"].get("ollama_model", "bge-m3")
BATCH = 48
TIMEOUT = 180
PRICE_PER_MTOK = 0.01  # bge-m3 на OpenRouter
RRF_K = 60
KEYWORD_RRF_WEIGHT = 0.5
STRONG_DIST = 0.85
SUPERSEDED_STATUSES = {"superseded", "deprecated"}
RAW_RRF_MULTIPLIER = 0.50
RAW_SOURCES = {
    "chatgpt", "gemini", "claude", "claude-code", "codex",
    "transcript", "inbox", "external",
}
FTS_STOPWORDS = {
    "і", "й", "та", "а", "але", "чи", "це", "як", "що", "я", "ми", "ти", "в", "у",
    "на", "до", "з", "із", "про", "для", "там", "щоб", "було", "бути", "мене", "мені",
    "и", "или", "это", "как", "что", "я", "мы", "ты", "в", "на", "для", "про", "быть",
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "is", "are", "this",
}

_usage_tokens = 0  # сумарні токени embed за прогін (для звіту вартості)
_read_only_connections: set[int] = set()

# Ранжування ланцюга знань: курований шар (самарі/memory) отримує знижку до відстані,
# щоб спливати ПЕРШИМ над дослівними сирими чатами. Множник <1 = ближче = вище.
# Без цього десятки тисяч сирих чанків завжди перекрикують жменю knowledge-чанків —
# ланцюг знань був би декларацією, а не поведінкою.
SOURCE_WEIGHT = {"knowledge": 0.82, "memory": 0.85, "tasks": 0.92, "vault": 0.94,
                 "chatgpt": 1.0, "gemini": 1.0, "claude": 1.0, "transcript": 1.05,
                 "inbox": 1.0, "claude-code": 1.0, "codex": 1.0, "external": 1.1}
# Сирі, неверифіковані шари — виводимо з банером недовіри (у самарі є ⚠️, у сирому нема).
UNVERIFIED_SRC = {"chatgpt": "⚠️ сирий чат ChatGPT — НЕ верифіковано (модель могла помилятись)",
                  "gemini": "⚠️ сира розмова з Gemini — НЕ верифіковано (модель могла помилятись)",
                  "claude": "⚠️ сирий чат Claude — не курований (сире ≠ канон)",
                  "inbox": "⚠️ сира надиктовка користувача з inbox — ще не розфасована",
                  "tasks": "📋 локальна task-система — стан дії дивись у frontmatter",
                  "claude-code": "⚠️ сира Claude Code-сесія — не курована",
                  "codex": "⚠️ сира Codex-сесія — не курована",
                  "transcript": "⚠️ сирий транскрипт — не куроване знання",
                  "external": "⚠️ зовнішнє знання — не верифіковано користувачем"}
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
    if ollama_alive():
        return "ollama"
    return "openrouter" if (OR_ENABLED and OR_FALLBACK) else "ollama"


def embed(texts: list[str], backend: str) -> list[list[float]]:
    """Обгортка над диспетчером: КОЖЕН реальний виклик лишає слід у журналі.

    🔴 22.08.2026. Не косметика. Агент, який каже «все локально, $0», доти був
    неперевірюваним: попередження про фолбек ішло в stderr, а Codex stderr не
    переказує — для людини різниці не було видно ніяк. Слід у журналі робить це
    твердження перевірюваним однією командою: `librarian.py usage`.

    🔴 Рушій береться з ФАКТУ виконання, а не з наміру: `resolve_engine()` до
    виклику може збрехати, якщо Ollama відвалиться між перевіркою і запитом.
    Тому диспетчер повертає, хто саме відпрацював."""
    vectors, engine = _embed_dispatch(texts, backend)
    embed_journal.record(engine, len(texts), sum(len(t) for t in texts),
                         command=" ".join(sys.argv[1:2]))
    return vectors


def _embed_dispatch(texts: list[str], backend: str) -> tuple[list[list[float]], str]:
    """Повертає (вектори, рушій-що-відпрацював)."""
    if backend == "ollama":
        return embed_ollama(texts), "ollama"
    if backend == "auto":
        if ollama_alive():
            try:
                return embed_ollama(texts), "ollama"
            except Exception as e:
                print(f"  [warn] ollama впав ({e})", file=sys.stderr)
        if not OR_ENABLED:
            sys.exit("ERROR: Ollama недоступний, а OpenRouter вимкнено "
                     "(embed.openrouter_enabled=false у config.toml). Два виходи: "
                     "підняти Ollama (`ollama serve`) АБО ввімкнути openrouter_enabled=true + ключ.")
        if not OR_FALLBACK:
            sys.exit("ERROR: Ollama недоступний. У мережу САМ не піду — це коштує грошей.\n"
                     "  • підняти Ollama:  ollama serve   (безкоштовно, тексти не покидають Mac)\n"
                     "  • цього разу через OpenRouter:  додай --backend openrouter\n"
                     "  • дозволити назавжди:  embed.openrouter_fallback = true у config.toml")
        print("  [warn] фолбек на OpenRouter — це платно (embed.openrouter_fallback=true)",
              file=sys.stderr)
        return embed_openrouter(texts), "openrouter"
    return embed_openrouter(texts), "openrouter"


# ─────────────────────────── db ───────────────────────────
def _load_vec(c: sqlite3.Connection) -> None:
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.enable_load_extension(False)


def connect(*, read_only: bool = False) -> sqlite3.Connection:
    """Read commands never require WAL/DDL or directory write access."""
    if read_only:
        uri = DB_PATH.resolve().as_uri()
        try:
            c = sqlite3.connect(f"{uri}?mode=ro", uri=True)
            c.execute("SELECT 1 FROM chunks LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            try:
                c.close()
            except UnboundLocalError:
                pass
            c = sqlite3.connect(f"{uri}?mode=ro&immutable=1", uri=True)
        _load_vec(c)
        c.execute("PRAGMA busy_timeout=5000")
        _read_only_connections.add(id(c))
        return c

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    _load_vec(c)
    # кілька писців (PreCompact-хук, ручні виклики) → WAL,
    # інакше рано чи пізно "database is locked"
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, source TEXT, ref TEXT, chunk_idx INTEGER, text TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_ref ON chunks(ref)")
    c.execute("CREATE TABLE IF NOT EXISTS files(ref TEXT PRIMARY KEY, source TEXT, sha TEXT, n_chunks INTEGER, indexed_at REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY, value TEXT)")
    existing_cols = {row[1] for row in c.execute("PRAGMA table_info(files)")}
    added_metadata = False
    for name, sql_type in (
        ("document_date", "TEXT"), ("date_source", "TEXT"),
        ("status", "TEXT"), ("superseded_by", "TEXT"), ("mtime", "REAL"),
    ):
        if name not in existing_cols:
            c.execute(f"ALTER TABLE files ADD COLUMN {name} {sql_type}")
            added_metadata = True
    c.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS vchunks USING vec0(embedding float[{DIM}])")
    fts_exists = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
    ).fetchone()
    c.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
        "ref, text, content='chunks', content_rowid='id', tokenize='unicode61')"
    )
    c.executescript("""
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
          INSERT INTO chunks_fts(rowid, ref, text) VALUES (new.id, new.ref, new.text);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
          INSERT INTO chunks_fts(chunks_fts, rowid, ref, text)
          VALUES ('delete', old.id, old.ref, old.text);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
          INSERT INTO chunks_fts(chunks_fts, rowid, ref, text)
          VALUES ('delete', old.id, old.ref, old.text);
          INSERT INTO chunks_fts(rowid, ref, text) VALUES (new.id, new.ref, new.text);
        END;
    """)
    if not fts_exists:
        c.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    version_row = c.execute(
        "SELECT value FROM schema_meta WHERE key='retrieval_schema_version'"
    ).fetchone()
    schema_version = int(version_row[0]) if version_row and version_row[0].isdigit() else 0
    if added_metadata or schema_version < 2:
        _backfill_file_metadata(c)
        c.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('retrieval_schema_version', '2')"
        )
    c.commit()
    return c


def _normalise_date(value: str | None) -> str | None:
    if not value:
        return None
    value = str(value).strip().strip('"\'')
    for pattern, fmt in (
        (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        (r"(\d{2}\.\d{2}\.\d{4})", "%d.%m.%Y"),
    ):
        match = re.search(pattern, value)
        if match:
            try:
                return datetime.strptime(match.group(1), fmt).date().isoformat()
            except ValueError:
                pass
    return None


def document_metadata(ref: str, text: str) -> dict:
    """Document-level metadata; mtime is explicitly a weak fallback, not fact time."""
    frontmatter = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                match = re.match(r"^\s*([\w-]+)\s*:\s*(.*?)\s*$", line)
                if match:
                    frontmatter[match.group(1).lower()] = match.group(2)
    document_date = None
    date_source = None
    for key in ("date", "created", "created_at", "updated", "updated_at"):
        document_date = _normalise_date(frontmatter.get(key))
        if document_date:
            date_source = f"frontmatter:{key}"
            break
    if not document_date:
        document_date = _normalise_date(Path(ref).name)
        if document_date:
            date_source = "filename"
    if not document_date:
        document_date = _normalise_date(text[:2000])
        if document_date:
            date_source = "content"
    mtime = None
    try:
        mtime = Path(ref).stat().st_mtime
    except OSError:
        pass
    if not document_date and mtime is not None:
        document_date = datetime.fromtimestamp(mtime).date().isoformat()
        date_source = "mtime"
    status = frontmatter.get("status", "active").strip().strip('"\'').lower() or "active"
    superseded_by = frontmatter.get("superseded_by") or frontmatter.get("superseded-by")
    if superseded_by:
        superseded_by = superseded_by.strip().strip('"\'')
    return {"document_date": document_date, "date_source": date_source,
            "status": status, "superseded_by": superseded_by, "mtime": mtime}


def _backfill_file_metadata(c: sqlite3.Connection) -> None:
    for (ref,) in c.execute("SELECT ref FROM files").fetchall():
        try:
            with Path(ref).open(encoding="utf-8", errors="ignore") as handle:
                text = handle.read(4000)
        except OSError:
            row = c.execute(
                "SELECT text FROM chunks WHERE ref=? ORDER BY chunk_idx LIMIT 1", (ref,)
            ).fetchone()
            text = row[0] if row else ""
        meta = document_metadata(ref, text)
        c.execute(
            "UPDATE files SET document_date=?, date_source=?, status=?, superseded_by=?, mtime=? "
            "WHERE ref=?",
            (meta["document_date"], meta["date_source"], meta["status"],
             meta["superseded_by"], meta["mtime"], ref),
        )


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


def gather_vault() -> list[tuple[str, str]]:
    """Root-level curated vault notes; linked archives are separate sources."""
    out = []
    if VAULT_DIR.exists():
        for fp in sorted(VAULT_DIR.glob("*.md")):
            if fp.name.startswith("_") or fp.is_symlink():
                continue
            try:
                out.append((str(fp), fp.read_text(encoding="utf-8")))
            except Exception:
                pass
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


def gather_external() -> list[tuple[str, str]]:
    """External raw/cards/distilled corpus with an explicit trust warning."""
    return gather_md_tree(EXTERNAL_DIR)


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


GATHER = {"memory": gather_memory, "vault": gather_vault, "transcript": gather_transcripts,
          "chatgpt": gather_chatgpt, "knowledge": gather_knowledge, "gemini": gather_gemini,
          "claude": gather_claude, "inbox": gather_inbox, "tasks": gather_tasks,
          "claude-code": gather_claude_code, "codex": gather_codex,
          "skills": gather_skills, "external": gather_external}


# ─────────────────────────── index ───────────────────────────
def index_source(c: sqlite3.Connection, source: str, backend: str, limit: int | None,
                 assume_yes: bool = False):
    docs = GATHER[source]()
    if limit:
        docs = docs[:limit]
    print(f"[{source}] файлів: {len(docs)}", file=sys.stderr)
    if resolve_engine(backend) == "openrouter":
        print(f"[OpenRouter] звертаюсь до ключа: embeddings {OR_MODEL} (індексація {source})", file=sys.stderr)
    else:
        print(f"[Ollama] локальний embed {OLLAMA_MODEL} (індексація {source}, $0)", file=sys.stderr)

    # ── спершу МІРЯЄМО роботу, і лише потім витрачаємо ───────────────────────
    # 🔴 23.08.2026: гейт вартості. Прохід перший нічого не ембедить — він рахує,
    #    скільки роботи насправді лишилось після пропуску незмінених файлів.
    #    Тримаємо ЧИСЛА, не тексти: інакше перевірка ціни коштувала б памʼяті
    #    більше, ніж сама індексація.
    plan: list[tuple] = []
    n_skip = 0
    pend_chunks = pend_chars = 0
    for ref, text in docs:
        sha = hashlib.sha1(text.encode("utf-8")).hexdigest()
        meta = document_metadata(ref, text)
        row = c.execute("SELECT sha FROM files WHERE ref=?", (ref,)).fetchone()
        if row and row[0] == sha:
            c.execute(
                "UPDATE files SET document_date=?, date_source=?, status=?, superseded_by=?, mtime=? "
                "WHERE ref=?",
                (meta["document_date"], meta["date_source"], meta["status"],
                 meta["superseded_by"], meta["mtime"], ref),
            )
            c.commit()
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
        tail = chunks[keep:]
        pend_chunks += len(tail)
        pend_chars += sum(len(ch) for ch in tail)
        plan.append((ref, text, sha, meta, keep, stale))

    cost_gate.gate(cost_gate.estimate(pend_chunks, pend_chars),
                   engine=resolve_engine(backend),
                   what=f"індексація {source}",
                   cfg=cost_gate.cfg_from(CFG.get("embed", {})),
                   assume_yes=assume_yes)

    n_new = n_chunks = 0
    for ref, text, sha, meta, keep, stale in plan:
        chunks = chunk_text(text)
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
        c.execute(
            "INSERT OR REPLACE INTO files("
            "ref, source, sha, n_chunks, indexed_at, document_date, date_source, status, superseded_by, mtime"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ref, source, sha, len(chunks), time.time(), meta["document_date"],
             meta["date_source"], meta["status"], meta["superseded_by"], meta["mtime"]),
        )
        c.commit()
        n_new += 1
        print(f"  + {Path(ref).name}  ({len(chunks)} чанків)", file=sys.stderr)

    print(f"[{source}] нових/змінених: {n_new}, пропущено (без змін): {n_skip}, чанків додано: {n_chunks}",
          file=sys.stderr)


def checkpoint_wal(c: sqlite3.Connection) -> None:
    """Злити WAL у основну базу й обрізати його.

    22.07.2026: база відкривається в journal_mode=WAL, але чекпоінт не робився
    ніде, і WAL ріс безмежно — на великій базі він здатен перегнати сам файл
    індексу. SQLite чекпоінтить сам лише коли остання конекція закривається
    «чисто», а фонові індекси з хука цього не гарантують.
    """
    try:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as exc:
        print(f"[wal] чекпоінт пропущено: {exc}", file=sys.stderr)


def cmd_index(sources: list[str], backend: str, limit: int | None,
              assume_yes: bool = False):
    c = connect()
    t0 = time.time()
    for s in sources:
        index_source(c, s, backend, limit, assume_yes)
    checkpoint_wal(c)
    c.close()
    dt = time.time() - t0
    if _usage_tokens:
        cost = _usage_tokens / 1e6 * PRICE_PER_MTOK
        print(f"\nГотово за {dt:.0f}с. Embed-токенів: {_usage_tokens:,} ≈ ${cost:.4f}", file=sys.stderr)
    else:
        print(f"\nГотово за {dt:.0f}с (локальний embed, $0).", file=sys.stderr)


def find_stale_refs(c: sqlite3.Connection, sources: list[str]) -> list[tuple[str, str]]:
    stale = []
    for source in sources:
        current = {ref for ref, _ in GATHER[source]()}
        indexed = {
            row[0] for row in c.execute(
                "SELECT ref FROM files WHERE source=? ORDER BY ref", (source,)
            )
        }
        stale.extend((source, ref) for ref in sorted(indexed - current))
    return stale


def cmd_prune(sources: list[str], apply: bool):
    c = connect(read_only=not apply)
    stale = find_stale_refs(c, sources)
    for source, ref in stale:
        print(f"{source}\t{ref}")
        if apply:
            ids = c.execute(
                "SELECT id FROM chunks WHERE source=? AND ref=?", (source, ref)
            ).fetchall()
            c.executemany("DELETE FROM vchunks WHERE rowid=?", ids)
            c.execute("DELETE FROM chunks WHERE source=? AND ref=?", (source, ref))
            c.execute("DELETE FROM files WHERE source=? AND ref=?", (source, ref))
    if apply:
        c.commit()
    c.close()
    print(f"{'REMOVED' if apply else 'DRY-RUN'} {len(stale)} stale refs")


# ─────────────────────────── search ───────────────────────────
def _fts_query(query: str) -> str | None:
    tokens = []
    for token in re.findall(r"[^\W_]+", query.lower(), flags=re.UNICODE):
        if len(token) < 2 or token in FTS_STOPWORDS or token in tokens:
            continue
        tokens.append(token)
        if len(tokens) >= 16:
            break
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens) or None


def _file_meta(c: sqlite3.Connection, ref: str) -> dict:
    row = c.execute(
        "SELECT document_date, date_source, status, superseded_by FROM files WHERE ref=?",
        (ref,),
    ).fetchone()
    if not row:
        return {"document_date": None, "date_source": None,
                "status": "active", "superseded_by": None}
    return {"document_date": row[0], "date_source": row[1],
            "status": row[2] or "active", "superseded_by": row[3]}


def _passes_filters(meta: dict, after: str | None, before: str | None,
                    include_undated: bool, include_superseded: bool) -> bool:
    if not include_superseded and meta["status"] in SUPERSEDED_STATUSES:
        return False
    if not after and not before:
        return True
    reliable = meta["document_date"] and meta["date_source"] != "mtime"
    if not reliable:
        return include_undated
    return not ((after and meta["document_date"] < after)
                or (before and meta["document_date"] > before))


def _recency_multiplier(meta: dict, prefer_recent: bool) -> float:
    if not prefer_recent or not meta["document_date"] or meta["date_source"] == "mtime":
        return 1.0
    try:
        age_days = max(0, (date.today() - date.fromisoformat(meta["document_date"])).days)
    except ValueError:
        return 1.0
    return 1.0 + 0.08 * math.exp(-age_days / 180.0)


def _diversify(items: list[dict], k: int, max_per_file: int) -> list[dict]:
    if max_per_file <= 0:
        return items[:k]
    selected, selected_ids, counts = [], set(), Counter()
    for pass_limit in range(1, max_per_file + 1):
        for item in items:
            if item["id"] in selected_ids or counts[item["ref"]] >= pass_limit:
                continue
            selected.append(item)
            selected_ids.add(item["id"])
            counts[item["ref"]] += 1
            if len(selected) >= k:
                return selected
    for item in items:
        if item["id"] not in selected_ids:
            selected.append(item)
            if len(selected) >= k:
                break
    return selected


def _readonly_vector_search(c: sqlite3.Connection, qv: list[float],
                            fetch: int) -> list[tuple[int, float]]:
    """Exact vec0 L2 ranking without a writable virtual-table cursor."""
    import numpy as np

    query = np.asarray(qv, dtype=np.float32)
    if query.shape != (DIM,):
        raise ValueError(f"expected query vector with {DIM} dimensions")
    ids_parts, distance_parts = [], []
    rows = c.execute(
        "SELECT c.size, c.validity, c.rowids, v.vectors "
        "FROM vchunks_chunks c "
        "JOIN vchunks_vector_chunks00 v ON v.rowid=c.chunk_id"
    )
    for size, validity, rowids, vectors in rows:
        ids = np.frombuffer(rowids, dtype="<i8", count=size)
        valid = np.unpackbits(
            np.frombuffer(validity, dtype=np.uint8), bitorder="little"
        )[:size].astype(bool)
        matrix = np.frombuffer(vectors, dtype="<f4", count=size * DIM).reshape(size, DIM)
        active = matrix[valid]
        if not active.size:
            continue
        ids_parts.append(ids[valid])
        distance_parts.append(np.linalg.norm(active - query, axis=1))
    if not ids_parts:
        return []
    ids = np.concatenate(ids_parts)
    distances = np.concatenate(distance_parts)
    take = min(fetch, len(ids))
    nearest = np.argpartition(distances, take - 1)[:take]
    nearest = nearest[np.argsort(distances[nearest], kind="stable")]
    return [(int(ids[i]), float(distances[i])) for i in nearest]


def search_index(c: sqlite3.Connection, query: str, qv: list[float] | None,
                 source: str | None, k: int, retrieval: str, max_per_file: int,
                 after: str | None, before: str | None, include_undated: bool,
                 include_superseded: bool, prefer_recent: bool) -> dict:
    fetch = min(4096, 2000 if (source or after or before) else max(k * 40, 400))
    vector_rows = []
    if retrieval in ("vector", "hybrid"):
        if qv is None:
            raise ValueError("vector/hybrid retrieval requires a query embedding")
        if id(c) in _read_only_connections:
            vector_rows = _readonly_vector_search(c, qv, fetch)
        else:
            vector_rows = c.execute(
                "SELECT v.rowid, v.distance FROM vchunks v "
                "WHERE v.embedding MATCH ? AND k=? ORDER BY v.distance",
                (sqlite_vec.serialize_float32(qv), fetch),
            ).fetchall()
    keyword_rows = []
    fts_query = _fts_query(query)
    if retrieval in ("keyword", "hybrid") and fts_query:
        keyword_rows = c.execute(
            "SELECT rowid, bm25(chunks_fts, 5.0, 1.0) AS score "
            "FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?",
            (fts_query, fetch),
        ).fetchall()

    combined, metadata_cache = {}, {}

    def get_item(rid: int) -> dict | None:
        if rid in combined:
            return combined[rid]
        row = c.execute(
            "SELECT source, ref, chunk_idx, text FROM chunks WHERE id=?", (rid,)
        ).fetchone()
        if not row:
            return None
        src, ref, idx, text = row
        if source and src != source:
            return None
        meta = metadata_cache.setdefault(ref, _file_meta(c, ref))
        if not _passes_filters(meta, after, before, include_undated, include_superseded):
            return None
        item = {"id": rid, "source": src, "ref": ref, "chunk_idx": idx, "text": text,
                "vector_distance": None, "vector_rank": None, "keyword_rank": None,
                "alternates": [], **meta}
        combined[rid] = item
        return item

    rank = 0
    for rid, distance in vector_rows:
        item = get_item(rid)
        if item:
            rank += 1
            item["vector_rank"] = rank
            item["vector_distance"] = float(distance)
    rank = 0
    for rid, _bm25 in keyword_rows:
        item = get_item(rid)
        if item:
            rank += 1
            item["keyword_rank"] = rank

    ranked = []
    for item in combined.values():
        authority = 1.0 / eff_weight(item["source"], item["ref"])
        if retrieval == "vector":
            score = 1.0 / max(item["vector_distance"] or 0.0, 1e-9)
            trust = 1.0
        else:
            score = (1.0 / (RRF_K + item["vector_rank"])
                     if item["vector_rank"] is not None else 0.0)
            if item["keyword_rank"] is not None:
                score += KEYWORD_RRF_WEIGHT / (RRF_K + item["keyword_rank"])
            trust = RAW_RRF_MULTIPLIER if item["source"] in RAW_SOURCES else 1.0
        recency = _recency_multiplier(item, prefer_recent)
        item["authority_multiplier"], item["trust_multiplier"] = authority, trust
        item["recency_multiplier"] = recency
        item["fusion_score"] = score * authority * trust * recency
        both = item["vector_rank"] is not None and item["keyword_rank"] is not None
        item["retrieval_reason"] = "both" if both else (
            "vector" if item["vector_rank"] is not None else "keyword")
        trusted_for_anchor = eff_warn(item["source"], item["ref"]) is None \
            or item["source"] == "tasks"
        semantic_strong = (item["vector_distance"] is not None
                           and item["vector_distance"] <= STRONG_DIST
                           and item["vector_rank"] <= 3)
        dual_agreement = (both and item["vector_distance"] is not None
                          and item["vector_distance"] <= 1.0
                          and item["vector_rank"] <= 3 and item["keyword_rank"] <= 3)
        item["confidence"] = "strong" if (
            trusted_for_anchor and item["status"] not in {"raw", *SUPERSEDED_STATUSES}
            and (semantic_strong or dual_agreement)
        ) else "weak"
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["fusion_score"], item["id"]))

    grouped, by_text = [], {}
    for item in ranked:
        if item["text"] in by_text:
            by_text[item["text"]]["alternates"].append({
                "source": item["source"], "ref": item["ref"], "chunk_idx": item["chunk_idx"]})
            continue
        by_text[item["text"]] = item
        grouped.append(item)
    public = []
    for item in _diversify(grouped, k, max_per_file):
        warning = eff_warn(item["source"], item["ref"])
        warnings = [warning] if warning else []
        if item["status"] in SUPERSEDED_STATUSES:
            warnings.append(f"status={item['status']}")
        public.append({
            "source": item["source"], "ref": item["ref"], "chunk_idx": item["chunk_idx"],
            "snippet": item["text"] if len(item["text"]) <= 600 else item["text"][:600] + "…",
            "vector_distance": item["vector_distance"], "vector_rank": item["vector_rank"],
            "keyword_rank": item["keyword_rank"], "fusion_score": round(item["fusion_score"], 10),
            "confidence": item["confidence"], "retrieval_reason": item["retrieval_reason"],
            "document_date": item["document_date"], "date_source": item["date_source"],
            "status": item["status"], "superseded_by": item["superseded_by"],
            "authority_multiplier": round(item["authority_multiplier"], 4),
            "trust_multiplier": round(item["trust_multiplier"], 4),
            "recency_multiplier": round(item["recency_multiplier"], 4),
            "warnings": warnings, "alternates": item["alternates"],
        })
    return {"query": query, "retrieval": retrieval, "results": public}


def cmd_search(query: str, source: str | None, k: int, backend: str,
               retrieval: str, output_format: str, max_per_file: int,
               after: str | None, before: str | None, include_undated: bool,
               include_superseded: bool, prefer_recent: bool):
    c = connect(read_only=True)
    qv = None
    if retrieval in ("vector", "hybrid"):
        if resolve_engine(backend) == "openrouter":
            print(f"[OpenRouter] звертаюсь до ключа: embeddings {OR_MODEL} (пошук-запит)", file=sys.stderr)
        else:
            print(f"[Ollama] локальний embed {OLLAMA_MODEL} (пошук-запит, $0)", file=sys.stderr)
        qv = embed([query], backend)[0]
    payload = search_index(c, query, qv, source, k, retrieval, max_per_file,
                           after, before, include_undated, include_superseded, prefer_recent)
    c.close()
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False))
        return
    if not payload["results"]:
        print("Нічого не знайдено.")
        return
    for item in payload["results"]:
        nm = Path(item["ref"]).name
        if nm == "SKILL.md":
            nm = f"{Path(item['ref']).parent.name}/SKILL.md"
        dist = item["vector_distance"]
        dist_label = f"{dist:.3f}" if dist is not None else "n/a"
        head = f"\n── [{item['source']}] {nm} #{item['chunk_idx']}  (dist {dist_label}) ──"
        head += (f"\n   ↳ {item['retrieval_reason']} · confidence={item['confidence']}"
                 f" · fusion={item['fusion_score']:.6f}"
                 f" · authority×{item['authority_multiplier']:.2f}"
                 f" · trust×{item['trust_multiplier']:.2f}"
                 f" · recency×{item['recency_multiplier']:.2f}")
        if item["document_date"]:
            head += f" · date={item['document_date']}({item['date_source']})"
        for warning in item["warnings"]:
            head += f"\n   {warning}"
        print(f"{head}\n{item['snippet']}")


def cmd_stats():
    c = connect(read_only=True)
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
                    choices=["memory", "vault", "transcripts", "chatgpt", "knowledge", "gemini", "claude", "inbox", "tasks", "claude-code", "codex", "skills", "external", "all"])
    pi.add_argument("--backend", default="auto", choices=["openrouter", "ollama", "auto"])
    pi.add_argument("--limit", type=int, default=None, help="обмежити к-сть файлів (для тесту)")
    pi.add_argument("--yes", action="store_true",
                    help="свідомо дозволити платний прогін без питання (гейт вартості)")
    ps = sub.add_parser("search")
    ps.add_argument("query")
    ps.add_argument("--source", default=None,
                    choices=["memory", "vault", "transcript", "chatgpt", "knowledge", "gemini", "claude", "inbox", "tasks", "claude-code", "codex", "skills", "external"])
    ps.add_argument("-k", type=int, default=8)
    ps.add_argument("--backend", default="auto", choices=["openrouter", "ollama", "auto"])
    ps.add_argument("--b64", action="store_true", help="query передано у base64 (shell-safe)")
    ps.add_argument("--retrieval", default="hybrid", choices=["vector", "hybrid", "keyword"])
    ps.add_argument("--format", default="text", choices=["text", "json"], dest="output_format")
    ps.add_argument("--max-per-file", type=int, default=2,
                    help="soft cap чанків одного файла; 0 вимикає")
    ps.add_argument("--after", type=_normalise_date, default=None, metavar="YYYY-MM-DD")
    ps.add_argument("--before", type=_normalise_date, default=None, metavar="YYYY-MM-DD")
    ps.add_argument("--include-undated", action="store_true")
    ps.add_argument("--include-superseded", action="store_true")
    ps.add_argument("--prefer-recent", action="store_true",
                    help="помірний boost лише для надійних дат; mtime не boost-иться")
    sub.add_parser("stats")
    pu = sub.add_parser("usage", help="журнал ембедингів: що реально відпрацювало і чи платили")
    pu.add_argument("--last", type=int, default=0, metavar="N",
                    help="лише останні N записів (0 = усі)")
    pp = sub.add_parser("prune", help="stale refs; dry-run unless --apply")
    pp.add_argument("--source", required=True,
                    choices=["memory", "vault", "transcripts", "chatgpt", "knowledge", "gemini", "claude", "inbox", "tasks", "claude-code", "codex", "skills", "external", "all"])
    pp.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if a.cmd == "index":
        srcs = list(GATHER) if a.source == "all" else \
               ["transcript" if a.source == "transcripts" else a.source]
        cmd_index(srcs, a.backend, a.limit, getattr(a, "yes", False))
    elif a.cmd == "search":
        q = a.query
        if a.b64:
            import base64
            q = base64.b64decode(q.encode("ascii")).decode("utf-8")
        if ("--after" in sys.argv and not a.after) or ("--before" in sys.argv and not a.before):
            ap.error("--after/--before очікує валідну дату YYYY-MM-DD або ДД.ММ.РРРР")
        cmd_search(q, a.source, a.k, a.backend, a.retrieval, a.output_format,
                   a.max_per_file, a.after, a.before, a.include_undated,
                   a.include_superseded, a.prefer_recent)
    elif a.cmd == "stats":
        cmd_stats()
    elif a.cmd == "usage":
        print(embed_journal.summary(a.last))
    elif a.cmd == "prune":
        srcs = list(GATHER) if a.source == "all" else \
               ["transcript" if a.source == "transcripts" else a.source]
        cmd_prune(srcs, a.apply)

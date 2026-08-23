# Changelog

## 3.0.0-beta.1 — 18.08.2026

### Тири: одна установка замість трьох

- **`TIERS.toml`** — маніфест шарів. Кожен файл репозиторію належить рівно одному
  тиру (v1/v2/v3) або інфраструктурі; `sbkit.py tiers --verify` це стереже.
  Тири строго вкладені: v1 ⊂ v2 ⊂ v3, жоден не перевизначає файли нижчого.
- **`sbkit.py install --tier`** тепер спершу дивиться, що вже лежить у корені:
  порожньо / вольт безкоштовної версії / уже встановлений Кит — і поводиться
  відповідно. Вольт безкоштовної версії **підхоплюється** (`status: adopted`):
  бекап, додавання керуючого шару, жодного видалення.
- **`sbkit.py upgrade --to v3`** піднімає тир окремо від версії Кита.
  Пониження заблоковане за замовчуванням (`--allow-downgrade` для явного випадку).
- **`sbkit.py tiers`** показує, що стоїть і які шари активні.
- Тир записується в `[kit].tier` конфіга та в `state.json` (+ `tier_history`).
- **Інваріант, який тепер під тестом:** «поставити одразу v3» і «пройти
  v1 → v2 → v3» дають ідентичний результат — `tests/test_tiers.py`.
- **`templates/tier-*.fragment.md`** — інструкція агента росте разом із тиром.
  Це і є справжня різниця між версіями, а не лише набір скриптів.
- **`install.sh`** — одна команда від нуля до працюючої бази, ідемпотентна
  й безпечна поверх наявних даних.
- Документація: `docs/19-tiers.md`.

### Тир v3: звід (сказане проти записаного)

- Агент звіряє сказане із записаним. Не входить у цю збірку — `sbkit.py tiers`.

## 2.0.0-beta.5 — 23.07.2026

- Added a Codex adapter for the anti-compact shield: `scripts/hooks/codex_lifecycle.py`
  is a single lifecycle hook dispatched by `hook_event_name`. Unlike the Claude Code
  adapter, Codex exposes a `PostCompact` event (recorded to a compaction log) and
  per-turn telemetry via `token_count` rollout events, so the hook reports context
  usage and 5-hour/weekly rate limits (`--status` prints them on demand and
  SessionStart injects a pressure note at ≥70/85%). PreCompact writes a per-session
  deterministic checkpoint (obligations, verbatim prompts, working paths, curated
  `bridge.md ## ЗАРАЗ`) with a machine `degraded` flag, parsed from Codex's own
  `rollout-*.jsonl` transcript format; SessionStart re-injects a fresh checkpoint of
  the same session. No LLM, no network, fail-open. Wiring in
  `scripts/hooks/codex-hooks.example.json`, docs in `docs/18-codex-hooks.md`.

## 2.0.0-beta.4 — 23.07.2026

- Added an anti-compact state snapshot: a new deterministic `pre_compact_snapshot.py`
  PreCompact hook writes an ephemeral checkpoint (current obligations, verbatim last
  prompts, working paths, curated `bridge.md ## ЗАРАЗ`) plus an audit line with a
  machine `degraded` flag. `session_start.sh` injects it back on the next session so
  the model re-anchors after compaction independently of model discipline. No LLM,
  no network, and it never breaks compaction (every path is guarded).
- Added task dependencies: `task.py` gains a `depends_on` field and `--depends-on`
  on `add`/`edit`. `due` now splits tasks whose dependencies are still open into a
  `BLOCKED` section instead of the actionable queue, and warns on dependency ids that
  exist nowhere without blocking. `list`/`due` no longer crash on a hand-edited
  malformed `due` date.

## 2.0.0-beta.3 — 22.07.2026

- Fixed PreCompact stacking: a long session with many compactions launched one
  full transcript index per compaction, and the runs piled up and hammered the
  embedding model in parallel (machine ran hot). The hook now takes an atomic
  `mkdir` lock and skips a compaction while an index is already running; a lock
  older than 30 minutes is treated as orphaned.
- Fixed unbounded WAL growth: `index` now ends with
  `PRAGMA wal_checkpoint(TRUNCATE)`. The write-ahead log was never checkpointed
  and on a large index it can outgrow the database file itself.
- Documented both symptoms in `docs/08-troubleshooting.md`.

## 2.0.0-beta.2 — 18.07.2026

- Fixed the supported macOS CI route by using Homebrew Python with loadable
  SQLite extensions.
- Verified the full test suite on macOS and Linux 3.11/3.13.

## 2.0.0-beta.1 — 18.07.2026

- Added snapshot-first `doctor`, `demo`, `install`, `migrate`, `upgrade`,
  `backup`, `restore`, `rollback`, and `health` lifecycle commands.
- Added versioned config/data state and V1 migration dry-run.
- Added hybrid retrieval, temporal metadata, JSON contract, source trust,
  diversity, read-only sandbox search, and stale-index pruning.
- Added full Markdown task lifecycle, external knowledge layer, Claude Code and
  Codex adapters, release audit, and installed-library health checks.
- Declared macOS-first support; Linux CLI is supported; Windows/WSL is not
  promised for 2.0.

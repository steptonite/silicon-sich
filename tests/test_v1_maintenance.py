"""Dependency-free V1 maintenance regressions."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

import sqlite_vec


KIT = Path(__file__).parents[1]


def vector(value=1.0):
    return [value] + [0.0] * 1023


class V1MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        config = root / "config.toml"
        config.write_text(f"""
[vault]
root = "{root}/vault"
memory = "{root}/memory"
inbox = "{root}/inbox"
tasks = "{root}/tasks"
[archives]
chatgpt = "{root}/chatgpt"
gemini = "{root}/gemini"
claude = "{root}/claude"
knowledge = "{root}/knowledge"
claude_code = "{root}/claude-code"
codex = "{root}/codex"
[claude_code]
projects_dir = "{root}/projects"
skills_dir = "{root}/skills"
[index]
db_path = "{root}/index.db"
[embed]
ollama_url = "http://localhost:11434"
ollama_model = "bge-m3"
openrouter_enabled = false
openrouter_model = "baai/bge-m3"
env_file = "{root}/.env"
""")
        os.environ["SB_CONFIG"] = str(config)
        sys.path.insert(0, str(KIT / "scripts"))
        sys.modules.pop("sb_config", None)
        spec = importlib.util.spec_from_file_location("v1_librarian_test", KIT / "scripts/librarian.py")
        self.lib = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(self.lib)
        self.lib.DB_PATH = root / "index.db"
        self.c = self.lib.connect()

    def tearDown(self):
        if self.c:
            self.c.close()
        self.tmp.cleanup()

    def test_read_only_search_needs_no_sidecars(self):
        self.c.execute(
            "INSERT INTO files(ref, source, sha, n_chunks, indexed_at) VALUES (?,?,?,?,?)",
            ("/memory/canon.md", "memory", "sha", 1, 0),
        )
        row = self.c.execute(
            "INSERT INTO chunks(source, ref, chunk_idx, text) VALUES (?,?,?,?)",
            ("memory", "/memory/canon.md", 0, "canonical"),
        ).lastrowid
        self.c.execute(
            "INSERT INTO vchunks(rowid, embedding) VALUES (?,?)",
            (row, sqlite_vec.serialize_float32(vector())),
        )
        self.c.commit()
        self.c.close()
        self.c = None
        db = self.lib.DB_PATH
        directory = db.parent
        db.chmod(0o444)
        directory.chmod(0o555)
        reader = None
        try:
            reader = self.lib.connect(read_only=True)
            # Ім'я функції розійшлось між публічною копією v1 (vector_search)
            # і джерелом (_readonly_vector_search) — властивість та сама:
            # пошук на read-only базі не має нічого дописувати. Тест стереже
            # ВЛАСТИВІСТЬ, тому приймає обидва імені, а не ламається на переїзді.
            search = getattr(self.lib, "vector_search", None) or self.lib._readonly_vector_search
            rows = search(reader, vector(), 1)
            self.assertEqual(rows[0][0], row)
            self.assertFalse(Path(f"{db}-wal").exists())
            self.assertFalse(Path(f"{db}-shm").exists())
        finally:
            if reader:
                reader.close()
            directory.chmod(0o700)
            db.chmod(0o600)


def _load_sbkit():
    spec = importlib.util.spec_from_file_location("sbkit_under_test", KIT / "sbkit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HooksExampleTests(unittest.TestCase):
    def test_every_hook_command_points_to_existing_file(self):
        import json
        import shlex
        data = json.loads((KIT / "scripts/hooks/settings-hooks.example.json").read_text())
        seen = 0
        for groups in data["hooks"].values():
            for group in groups:
                for hook in group["hooks"]:
                    seen += 1
                    tokens = shlex.split(hook["command"].replace("<KIT>", str(KIT)))
                    scripts = [t for t in tokens if t.endswith((".sh", ".py"))]
                    self.assertTrue(scripts, hook["command"])
                    for script in scripts:
                        self.assertTrue(Path(script).exists(), f"нема файлу: {script}")
        self.assertGreaterEqual(seen, 5)


class MarkdownLinksTests(unittest.TestCase):
    def test_relative_md_links_resolve(self):
        import re
        skip = {".git", ".venv", "node_modules", "fixtures"}
        pattern = re.compile(r"\]\(([^)\s#]+\.md)(?:#[^)]*)?\)")
        broken = []
        for md in KIT.rglob("*.md"):
            if skip & set(md.relative_to(KIT).parts):
                continue
            text = md.read_text(encoding="utf-8", errors="replace")
            text = re.sub(r"```.*?```", "", text, flags=re.S)       # приклади в коді — не посилання
            text = re.sub(r"`[^`\n]*`", "", text)
            for target in pattern.findall(text):
                if "://" in target or target.startswith("mailto:"):
                    continue
                if not (md.parent / target).resolve().exists():
                    broken.append(f"{md.relative_to(KIT)} -> {target}")
        self.assertEqual(broken, [])


class HooksInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.settings = self.home / ".claude" / "settings.json"
        self.sbkit = _load_sbkit()

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self):
        import subprocess
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run(
            [sys.executable, str(KIT / "sbkit.py"), "hooks", "install", "--agent", "claude"],
            env=env, capture_output=True, text=True)

    def test_merge_keeps_foreign_and_is_idempotent(self):
        import json
        self.settings.parent.mkdir(parents=True)
        foreign = {"type": "command", "command": "echo foreign"}
        self.settings.write_text(json.dumps({
            "theme": "dark",
            "hooks": {"PreCompact": [{"hooks": [foreign]}], "Stop": [{"hooks": [foreign]}]},
        }))
        first = self.run_install()
        self.assertEqual(first.returncode, 0, first.stderr)
        data = json.loads(self.settings.read_text())
        self.assertEqual(data["theme"], "dark")
        self.assertIn(foreign, data["hooks"]["Stop"][0]["hooks"])
        self.assertIn(foreign, data["hooks"]["PreCompact"][0]["hooks"])
        commands = [h["command"] for gs in data["hooks"].values() for g in gs for h in g["hooks"]]
        self.assertTrue(any("pre_compact.sh" in c for c in commands))
        self.assertFalse(any("<KIT>" in c for c in commands))
        backups = list(self.settings.parent.glob("settings.json.sbkit-bak-*"))
        self.assertEqual(len(backups), 1)
        snapshot = self.settings.read_text()
        second = self.run_install()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.settings.read_text(), snapshot)          # нічого не продубльовано
        self.assertEqual(len(list(self.settings.parent.glob("settings.json.sbkit-bak-*"))), 1)

    def test_fresh_home_creates_settings_and_invalid_json_untouched(self):
        self.assertEqual(self.run_install().returncode, 0)
        self.assertTrue(self.settings.exists())
        self.settings.write_text("{ not json")
        res = self.run_install()
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(self.settings.read_text(), "{ not json")

    def test_doctor_flags_missing_claude_hooks(self):
        import contextlib
        import io
        import json
        from types import SimpleNamespace
        sb = self.sbkit
        sb.HOOK_MARKERS = {"claude": (self.settings, sb.HOOK_MARKERS["claude"][1])}
        sb.load_state = lambda root: {"agents": ["claude"], "tier": "v1"}

        def report():
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = sb.cmd_doctor(SimpleNamespace(config=None, root=str(self.home)))
            return code, json.loads(buf.getvalue())

        code, rep = report()                                   # settings.json нема -> None
        self.assertIsNone(rep["hooks"]["claude"])
        self.assertFalse(rep["ready"])
        self.assertNotEqual(code, 0)
        self.assertTrue(any("hooks install" in i for i in rep["issues"]))
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({"hooks": {"PreCompact": [{"hooks": [
            {"type": "command", "command": "bash /x/scripts/hooks/pre_compact.sh"}]}]}}))
        _, rep = report()
        self.assertTrue(rep["hooks"]["claude"])
        self.assertFalse(any("хуки для claude" in i for i in rep["issues"]))


if __name__ == "__main__":
    unittest.main()

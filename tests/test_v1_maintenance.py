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


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load_script("audit_one_plus_five")
snapshot = load_script("create_private_migration_snapshot")


class OnePlusFiveRegistryTests(unittest.TestCase):
    def test_registry_has_exactly_five_valid_projects(self):
        registry = audit.load_registry()
        errors, _warnings = audit.validate_registry(ROOT, registry)
        self.assertEqual([], errors)
        self.assertEqual(5, len(registry["projects"]))
        self.assertEqual(
            {
                "china_macro",
                "us_macro",
                "abdc_research",
                "research_tools",
                "personal_tools",
            },
            {project["id"] for project in registry["projects"]},
        )

    def test_high_confidence_scanner_does_not_return_secret_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / "candidate.txt"
            candidate.write_text(
                "token=" + "ghp_" + ("a" * 36) + "\n",
                encoding="utf-8",
            )
            findings = audit.scan_high_confidence_secrets(
                root, ["candidate.txt"]
            )
            self.assertEqual("github_token", findings[0]["kind"])
            self.assertNotIn("ghp_", json.dumps(findings))

    def test_server_supports_side_effect_limited_restore_smoke(self):
        server_text = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("os.environ.get('PBOC_AUTO', '1') != '0'", server_text)


class PrivateSnapshotTests(unittest.TestCase):
    def _registry(self):
        return {
            "shared": {
                "private_data_globs": [".secrets", "data/**"],
            },
            "projects": [],
        }

    def test_snapshot_copies_files_and_uses_sqlite_backup(self):
        with tempfile.TemporaryDirectory() as source_temp, tempfile.TemporaryDirectory() as dest_temp:
            source = Path(source_temp)
            destination = Path(dest_temp)
            (source / "data").mkdir()
            (source / ".secrets").write_text("TOKEN=test-only\n", encoding="utf-8")
            (source / "data" / "blob.bin").write_bytes(b"research-data")
            database = source / "data" / "sample.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE sample(value TEXT)")
            connection.execute("INSERT INTO sample VALUES ('ok')")
            connection.commit()
            connection.close()

            result = snapshot.create_snapshot(
                source,
                destination,
                "test-snapshot",
                self._registry(),
            )
            copied_db = result / "workspace" / "data" / "sample.db"
            copied = sqlite3.connect(copied_db)
            self.assertEqual("ok", copied.execute("SELECT value FROM sample").fetchone()[0])
            copied.close()
            self.assertEqual(
                b"research-data",
                (result / "workspace" / "data" / "blob.bin").read_bytes(),
            )
            manifest = json.loads(
                (result / "migration-manifest.json").read_text(encoding="utf-8")
            )
            methods = {entry["path"]: entry["method"] for entry in manifest["files"]}
            self.assertEqual("sqlite_backup", methods["data/sample.db"])
            self.assertEqual("resumable_copy", methods["data/blob.bin"])

    def test_triplet_fallback_includes_nonempty_wal(self):
        with tempfile.TemporaryDirectory() as source_temp, tempfile.TemporaryDirectory() as dest_temp:
            source = Path(source_temp)
            destination = Path(dest_temp) / "copied.db"
            database = source / "wal.db"
            connection = sqlite3.connect(database)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("CREATE TABLE sample(value TEXT)")
            connection.execute("INSERT INTO sample VALUES ('from-wal')")
            connection.commit()
            self.assertGreater(Path(str(database) + "-wal").stat().st_size, 0)

            part = destination.with_name(destination.name + ".part")
            digest, size = snapshot.backup_sqlite_from_triplet(
                database, part, destination
            )
            self.assertEqual(64, len(digest))
            self.assertGreater(size, 0)
            copied = sqlite3.connect(destination)
            self.assertEqual(
                "from-wal",
                copied.execute("SELECT value FROM sample").fetchone()[0],
            )
            copied.close()
            connection.close()

    def test_snapshot_rejects_destination_inside_repository(self):
        with tempfile.TemporaryDirectory() as source_temp:
            source = Path(source_temp)
            (source / "data").mkdir()
            (source / "data" / "blob.bin").write_bytes(b"x")
            with self.assertRaises(ValueError):
                snapshot.create_snapshot(
                    source,
                    source / "backup",
                    "invalid",
                    self._registry(),
                )


if __name__ == "__main__":
    unittest.main()

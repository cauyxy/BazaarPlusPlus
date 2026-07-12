import tempfile
import unittest
from pathlib import Path

from backend.bpp.settings import LaunchOptionsBackup, LaunchOptionsBackupStore


class LaunchOptionsBackupStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.settings_dir = Path(self.temporary.name)
        self.store = LaunchOptionsBackupStore(self.settings_dir)

    def tearDown(self):
        self.temporary.cleanup()

    def test_reads_existing_compatible_backup(self):
        (self.settings_dir / "launch-options.json").write_text(
            '{"original":"%command%","managed":"managed"}', "utf-8"
        )
        self.assertEqual(
            self.store.get(),
            LaunchOptionsBackup(original="%command%", managed="managed"),
        )

    def test_ignores_invalid_backup(self):
        path = self.settings_dir / "launch-options.json"
        for invalid in ("{", "[]", '{"original":1,"managed":"managed"}'):
            with self.subTest(invalid=invalid):
                path.write_text(invalid, "utf-8")
                self.assertIsNone(self.store.get())

    def test_enforces_length_boundary(self):
        self.store.save("a" * 16384, "b" * 16384)
        self.assertEqual(
            self.store.get(),
            LaunchOptionsBackup(original="a" * 16384, managed="b" * 16384),
        )
        with self.assertRaisesRegex(RuntimeError, "启动参数过长"):
            self.store.save("a" * 16385, "managed")
        with self.assertRaisesRegex(RuntimeError, "启动参数过长"):
            self.store.save("original", "b" * 16385)

    def test_clear_removes_backup(self):
        self.store.save("original", "managed")
        self.store.clear()
        self.assertIsNone(self.store.get())

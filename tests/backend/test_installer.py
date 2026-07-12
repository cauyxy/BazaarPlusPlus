import io
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from backend.bpp import installer
from backend.bpp.models import Release


class UnusedReleaseSource:
    def latest(self):
        raise AssertionError("not used")

    def acquire_payload(self, release, working_dir, progress):
        raise AssertionError("not used")


class ArchiveSafetyTests(unittest.TestCase):
    def _archive(self, entries):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, contents in entries:
                archive.writestr(name, contents)
        buffer.seek(0)
        return zipfile.ZipFile(buffer)

    def test_rejects_parent_absolute_and_symlink_entries(self):
        symlink = zipfile.ZipInfo("link")
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        for entry in ("../outside", "/absolute"):
            with self.subTest(entry=entry), self._archive([(entry, b"bad")]) as archive:
                with self.assertRaisesRegex(RuntimeError, "不安全路径"):
                    installer._safe_zip_members(archive)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(symlink, "target")
        buffer.seek(0)
        with zipfile.ZipFile(buffer) as archive, self.assertRaisesRegex(
            RuntimeError, "不安全路径"
        ):
            installer._safe_zip_members(archive)

    def test_rejects_extracted_size_over_limit(self):
        with self._archive([("large", b"12345")]) as archive, mock.patch.object(
            installer, "MAX_EXTRACTED_BYTES", 4
        ), self.assertRaisesRegex(RuntimeError, "安全大小限制"):
            installer._safe_zip_members(archive)


class PayloadVersionTests(unittest.TestCase):
    def _extract(self, payload_version, expected_version):
        entries = [
            ("winhttp.dll", b"dll"),
            ("doorstop_config.ini", b"config"),
            ("BepInEx/plugins/BazaarPlusPlus.dll", b"plugin"),
            ("BepInEx/plugins/BazaarPlusPlus.version", payload_version),
        ]
        with tempfile.TemporaryDirectory() as root_name:
            archive_path = Path(root_name) / "payload.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                for name, contents in entries:
                    archive.writestr(name, contents)
            staging = Path(root_name) / "staging"
            staging.mkdir()
            installer._extract_payload(archive_path, staging, expected_version)

    def test_accepts_exact_and_prod_versions(self):
        for payload_version in (b"1.2.3", b"1.2.3.prod", b"1.2.3.PrOd"):
            with self.subTest(payload_version=payload_version):
                self._extract(payload_version, "1.2.3")

    def test_rejects_invalid_versions(self):
        for payload_version in (b"1.2.4", b"  \n", b"1.2.3\xff"):
            with self.subTest(payload_version=payload_version), self.assertRaises(
                RuntimeError
            ):
                self._extract(payload_version, "1.2.3")

    def test_rejects_payload_missing_required_file(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            payload = root / "payload.zip"
            with zipfile.ZipFile(payload, "w") as archive:
                archive.writestr("winhttp.dll", b"dll")
            staging = root / "staging"
            staging.mkdir()
            with self.assertRaisesRegex(RuntimeError, "缺少"):
                installer._extract_payload(payload, staging, "1.2.3")


class InstallTransactionTests(unittest.TestCase):
    def _trees(self, root: Path):
        game = root / "game"
        staging = root / "staging"
        (game / "BepInEx/config").mkdir(parents=True)
        (game / "BepInEx/plugins").mkdir(parents=True)
        (staging / "BepInEx/plugins").mkdir(parents=True)
        (game / installer.BPP_CONFIG).write_text("saved=true", "utf-8")
        (staging / "BepInEx/config").mkdir(parents=True)
        (staging / installer.BPP_CONFIG).write_text("default=false", "utf-8")
        (game / "BepInEx/plugins/OtherMod.dll").write_bytes(b"other")
        (game / "BepInEx/plugins/BazaarPlusPlus.dll").write_bytes(b"old")
        (game / "BepInEx/plugins/System.Memory.dll").write_bytes(b"stale")
        (staging / "BepInEx/plugins/BazaarPlusPlus.dll").write_bytes(b"new")
        (staging / "BepInEx/plugins/BazaarPlusPlus.version").write_text(
            "9.9.9", "utf-8"
        )
        (staging / "winhttp.dll").write_bytes(b"doorstop")
        (staging / "doorstop_config.ini").write_text("enabled=true", "utf-8")
        return game, staging

    def test_install_preserves_config_and_other_plugins_and_removes_stale(self):
        with tempfile.TemporaryDirectory() as root_name:
            game, staging = self._trees(Path(root_name))
            installer._apply_staged_payload(staging, game)
            self.assertEqual(
                (game / "BepInEx/plugins/BazaarPlusPlus.dll").read_bytes(), b"new"
            )
            self.assertEqual((game / installer.BPP_CONFIG).read_text(), "saved=true")
            self.assertTrue((game / "BepInEx/plugins/OtherMod.dll").is_file())
            self.assertFalse((game / "BepInEx/plugins/System.Memory.dll").exists())

    def test_write_failure_rolls_back_replaced_and_stale_files(self):
        with tempfile.TemporaryDirectory() as root_name:
            game, staging = self._trees(Path(root_name))
            real_replace = os.replace
            calls = 0

            def fail_second(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected write failure")
                return real_replace(source, destination)

            with mock.patch.object(installer.os, "replace", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "injected write failure"):
                    installer._apply_staged_payload(staging, game)
            self.assertEqual(
                (game / "BepInEx/plugins/BazaarPlusPlus.dll").read_bytes(), b"old"
            )
            self.assertEqual(
                (game / "BepInEx/plugins/System.Memory.dll").read_bytes(), b"stale"
            )
            self.assertEqual(list(game.rglob("*.bpp-new")), [])

    def test_backup_failure_does_not_touch_game(self):
        with tempfile.TemporaryDirectory() as root_name:
            game, staging = self._trees(Path(root_name))
            with mock.patch.object(
                installer.shutil, "copy2", side_effect=OSError("backup failed")
            ), self.assertRaisesRegex(OSError, "backup failed"):
                installer._apply_staged_payload(staging, game)
            self.assertEqual(
                (game / "BepInEx/plugins/BazaarPlusPlus.dll").read_bytes(), b"old"
            )

    def test_rollback_failure_is_not_silently_swallowed(self):
        with tempfile.TemporaryDirectory() as root_name:
            game, staging = self._trees(Path(root_name))
            real_copy = installer.shutil.copy2
            copy_calls = 0

            def fail_write_and_rollback(source, destination, *args, **kwargs):
                nonlocal copy_calls
                copy_calls += 1
                if copy_calls == 6:
                    raise OSError("write failed")
                if copy_calls > 6:
                    raise OSError("rollback failed")
                return real_copy(source, destination, *args, **kwargs)

            with mock.patch.object(
                installer.shutil, "copy2", side_effect=fail_write_and_rollback
            ), self.assertRaises(OSError) as raised:
                installer._apply_staged_payload(staging, game)
            self.assertIn(str(raised.exception), {"write failed", "rollback failed"})


class InstallerOrchestrationTests(unittest.TestCase):
    def test_install_acquires_validates_applies_and_reports_progress(self):
        class PayloadReleaseSource:
            def latest(self):
                raise AssertionError("not used")

            def acquire_payload(self, release, working_dir, progress):
                progress("准备安全解包工具", 12)
                progress("下载官方安装包", 15)
                progress("提取 BepInEx payload", 74)
                payload = working_dir / "payload.zip"
                with zipfile.ZipFile(payload, "w") as archive:
                    archive.writestr("winhttp.dll", b"dll")
                    archive.writestr("doorstop_config.ini", b"config")
                    archive.writestr(
                        "BepInEx/plugins/BazaarPlusPlus.dll", b"plugin"
                    )
                    archive.writestr(
                        "BepInEx/plugins/BazaarPlusPlus.version", release.version
                    )
                return payload

        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            game = root / "game"
            game.mkdir()
            progress = []
            target = installer.Installer(PayloadReleaseSource())
            target.install(
                Release("4.4.3", "https://example.invalid/installer.exe"),
                game,
                root / "runtime",
                lambda message, percent: progress.append((message, percent)),
            )
            self.assertEqual(target.installed_version(game), "4.4.3")
            self.assertEqual(
                progress,
                [
                    ("准备安全解包工具", 12),
                    ("下载官方安装包", 15),
                    ("提取 BepInEx payload", 74),
                    ("校验安装内容", 82),
                    ("写入游戏目录", 90),
                    ("安装完成", 100),
                ],
            )

    def test_rejects_symlink_destination_directory(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            game = root / "game"
            staging = root / "staging"
            outside = root / "outside"
            game.mkdir()
            staging.mkdir()
            outside.mkdir()
            (game / "BepInEx").symlink_to(outside, target_is_directory=True)
            (staging / "BepInEx/plugins").mkdir(parents=True)
            (staging / "BepInEx/plugins/file.dll").write_bytes(b"data")
            with self.assertRaisesRegex(RuntimeError, "符号链接目录"):
                installer._apply_staged_payload(staging, game)

    def test_rejects_absolute_and_parent_destinations(self):
        with self.assertRaisesRegex(RuntimeError, "不安全路径"):
            installer._assert_safe_destination(Path("/game"), Path("/outside"))
        with self.assertRaisesRegex(RuntimeError, "不安全路径"):
            installer._assert_safe_destination(Path("/game"), Path("../outside"))

    def test_plugin_directory_counts_as_third_party(self):
        with tempfile.TemporaryDirectory() as root_name:
            game = Path(root_name)
            (game / "BepInEx/plugins/SomeOtherMod").mkdir(parents=True)
            self.assertTrue(installer._third_party_plugins(game))

    def test_reset_refuses_symlink_data_directory(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            game = root / "game"
            outside = root / "outside"
            game.mkdir()
            outside.mkdir()
            (game / installer.DATA_DIRECTORY).symlink_to(
                outside, target_is_directory=True
            )
            with self.assertRaisesRegex(RuntimeError, "符号链接"):
                installer.Installer(UnusedReleaseSource()).reset_data(game)

import threading
import time
import unittest
from pathlib import Path

from backend.bpp.application import BazaarPlusPlusManager
from backend.bpp.models import LatestRelease, PluginStatus, Release
from tests.backend.fakes import FakeInstaller, FakeReleaseSource, FakeSteamEnvironment


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.game = Path("/game")
        self.steam = FakeSteamEnvironment(self.game)
        self.releases = FakeReleaseSource(
            Release(
                "4.4.3",
                "https://bppinstaller.bazaarplusplus.com/4.4.3/"
                "windows-x86_64/updater/a.exe",
            )
        )
        self.installer = FakeInstaller("4.4.2.prod")
        self.manager = BazaarPlusPlusManager(
            self.steam, self.releases, self.installer, Path("/runtime")
        )

    def test_status_returns_value_object(self):
        self.assertEqual(
            self.manager.status(),
            PluginStatus(True, "/game", False, True, "4.4.2.prod"),
        )

    def test_latest_detects_normalized_match_and_update(self):
        self.assertEqual(
            self.manager.check_latest(), LatestRelease("4.4.3", True)
        )
        self.installer.version = "4.4.3.prod"
        self.assertEqual(
            self.manager.check_latest(), LatestRelease("4.4.3", False)
        )

    def test_latest_is_not_available_when_game_or_mod_is_missing(self):
        self.installer.version = None
        self.assertFalse(self.manager.check_latest().update_available)
        self.steam.game_path = None
        self.installer.version = "4.4.2"
        self.assertFalse(self.manager.check_latest().update_available)

    def test_mutations_return_fresh_status(self):
        progress = []
        self.assertEqual(
            self.manager.install(lambda message, percent: progress.append((message, percent))),
            PluginStatus(True, "/game", False, True, "4.4.3"),
        )
        self.assertEqual(progress[0], ("读取官方发布信息", 5))
        self.assertEqual(self.manager.uninstall().installed, False)
        self.manager.reset_data()
        self.assertEqual(
            self.installer.calls,
            [("install", self.game), ("uninstall", self.game), ("reset_data", self.game)],
        )

    def test_preflight_errors_before_mutation(self):
        self.steam.game_path = None
        with self.assertRaisesRegex(RuntimeError, "未找到"):
            self.manager.install(lambda message, percent: None)
        self.assertEqual(self.installer.calls, [])
        self.steam.game_path = self.game
        self.steam.running = True
        with self.assertRaisesRegex(RuntimeError, "仍在运行"):
            self.manager.uninstall()
        self.assertEqual(self.installer.calls, [])

    def test_mutation_lock_serializes_operations(self):
        active = 0
        maximum = 0
        active_lock = threading.Lock()
        original_install = self.installer.install

        def slow_install(*args):
            nonlocal active, maximum
            with active_lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.03)
            original_install(*args)
            with active_lock:
                active -= 1

        self.installer.install = slow_install
        errors = []

        def run():
            try:
                self.manager.install(lambda message, percent: None)
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=run), threading.Thread(target=run)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(maximum, 1)

    def test_mutation_lock_is_released_after_failure(self):
        self.steam.game_path = None
        with self.assertRaises(RuntimeError):
            self.manager.uninstall()
        self.steam.game_path = self.game
        self.manager.uninstall()

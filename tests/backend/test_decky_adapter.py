import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


decky = types.ModuleType("decky")
decky.DECKY_USER_HOME = "/home/deck"
decky.DECKY_PLUGIN_RUNTIME_DIR = "/tmp/bpp-runtime"
decky.DECKY_PLUGIN_SETTINGS_DIR = "/tmp/bpp-settings"
decky.logger = types.SimpleNamespace(info=lambda *args, **kwargs: None)
decky.emit = mock.AsyncMock()
sys.modules.setdefault("decky", decky)

from backend.bpp import decky_adapter
from backend.bpp.models import LatestRelease, PluginStatus
from backend.bpp.settings import LaunchOptionsBackup


STATUS = PluginStatus(True, "/game", False, True, "4.4.3.prod")


class FakeManager:
    def status(self):
        return STATUS

    def check_latest(self):
        return LatestRelease("4.4.3", False)

    def install(self, progress):
        progress("读取官方发布信息", 5)
        progress("安装完成", 100)
        return STATUS

    def uninstall(self):
        return PluginStatus(True, "/game", False, False, None)

    def reset_data(self):
        return STATUS


class FakeStore:
    def __init__(self):
        self.backup = None

    def save(self, original, managed):
        self.backup = LaunchOptionsBackup(original, managed)

    def get(self):
        return self.backup

    def clear(self):
        self.backup = None


class DeckyAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.plugin = decky_adapter.Plugin()
        self.plugin._loop = asyncio.get_running_loop()
        self.plugin._manager = FakeManager()
        self.plugin._settings = FakeStore()
        decky.emit.reset_mock()

    async def test_status_and_latest_wire_shapes(self):
        self.assertEqual(
            await self.plugin.get_status(),
            {
                "game_found": True,
                "game_path": "/game",
                "game_running": False,
                "installed": True,
                "installed_version": "4.4.3.prod",
            },
        )
        self.assertEqual(
            await self.plugin.check_latest(),
            {"version": "4.4.3", "update_available": False},
        )

    async def test_rpc_methods_delegate_and_serialize(self):
        self.assertFalse((await self.plugin.uninstall_mod())["installed"])
        self.assertTrue((await self.plugin.reset_data())["installed"])
        await self.plugin.remember_launch_options("original", "managed")
        self.assertEqual(
            await self.plugin.get_launch_options_backup(),
            {"original": "original", "managed": "managed"},
        )
        await self.plugin.clear_launch_options_backup()
        self.assertIsNone(await self.plugin.get_launch_options_backup())

    async def test_install_bridges_progress_from_worker_thread(self):
        result = await self.plugin.install_latest()
        self.assertTrue(result["installed"])
        self.assertEqual(
            decky.emit.await_args_list,
            [
                mock.call("install_progress", "读取官方发布信息", 5),
                mock.call("install_progress", "安装完成", 100),
            ],
        )

    async def test_root_entrypoint_exposes_same_plugin(self):
        import main

        self.assertIs(main.Plugin, decky_adapter.Plugin)
        self.assertEqual(main.__all__, ["Plugin"])

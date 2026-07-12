import asyncio
from pathlib import Path

import decky

from .application import BazaarPlusPlusManager
from .installer import Installer
from .models import LatestRelease, PluginStatus
from .release import OfficialReleaseSource
from .settings import LaunchOptionsBackupStore
from .steam import LinuxSteamEnvironment


def _status_to_wire(status: PluginStatus) -> dict[str, object]:
    return {
        "game_found": status.game_found,
        "game_path": status.game_path,
        "game_running": status.game_running,
        "installed": status.installed,
        "installed_version": status.installed_version,
    }


def _latest_to_wire(latest: LatestRelease) -> dict[str, object]:
    return {
        "version": latest.version,
        "update_available": latest.update_available,
    }


class Plugin:
    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        runtime_dir = Path(decky.DECKY_PLUGIN_RUNTIME_DIR)
        settings_dir = Path(decky.DECKY_PLUGIN_SETTINGS_DIR)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        settings_dir.mkdir(parents=True, exist_ok=True)
        releases = OfficialReleaseSource(runtime_dir)
        installer = Installer(releases)
        self._manager = BazaarPlusPlusManager(
            steam=LinuxSteamEnvironment(Path(decky.DECKY_USER_HOME)),
            releases=releases,
            installer=installer,
            runtime_dir=runtime_dir,
        )
        self._settings = LaunchOptionsBackupStore(settings_dir)
        decky.logger.info("BazaarPlusPlus Steam Deck plugin loaded")

    async def _unload(self) -> None:
        decky.logger.info("BazaarPlusPlus Steam Deck plugin unloaded")

    async def get_status(self) -> dict[str, object]:
        return _status_to_wire(await asyncio.to_thread(self._manager.status))

    async def check_latest(self) -> dict[str, object]:
        return _latest_to_wire(await asyncio.to_thread(self._manager.check_latest))

    async def install_latest(self) -> dict[str, object]:
        def progress(message: str, percent: int) -> None:
            future = asyncio.run_coroutine_threadsafe(
                decky.emit("install_progress", message, percent), self._loop
            )
            future.result()

        status = await asyncio.to_thread(self._manager.install, progress)
        decky.logger.info("Installed BazaarPlusPlus to %s", status.game_path)
        return _status_to_wire(status)

    async def uninstall_mod(self) -> dict[str, object]:
        status = await asyncio.to_thread(self._manager.uninstall)
        decky.logger.info("Uninstalled BazaarPlusPlus from %s", status.game_path)
        return _status_to_wire(status)

    async def reset_data(self) -> dict[str, object]:
        status = await asyncio.to_thread(self._manager.reset_data)
        decky.logger.info("Reset BazaarPlusPlus data at %s", status.game_path)
        return _status_to_wire(status)

    async def remember_launch_options(self, original: str, managed: str) -> None:
        await asyncio.to_thread(self._settings.save, original, managed)

    async def get_launch_options_backup(self) -> dict[str, str] | None:
        backup = await asyncio.to_thread(self._settings.get)
        if backup is None:
            return None
        return {"original": backup.original, "managed": backup.managed}

    async def clear_launch_options_backup(self) -> None:
        await asyncio.to_thread(self._settings.clear)

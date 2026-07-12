import threading
from pathlib import Path

from .installer import Installer
from .models import LatestRelease, PluginStatus, normalize_version
from .release import ProgressReporter, ReleaseSource
from .steam import SteamEnvironment


class BazaarPlusPlusManager:
    def __init__(
        self,
        steam: SteamEnvironment,
        releases: ReleaseSource,
        installer: Installer,
        runtime_dir: Path,
    ) -> None:
        self._steam = steam
        self._releases = releases
        self._installer = installer
        self._runtime_dir = runtime_dir
        self._mutation_lock = threading.Lock()

    def status(self) -> PluginStatus:
        game_path = self._steam.find_game()
        installed_version = (
            self._installer.installed_version(game_path) if game_path else None
        )
        return PluginStatus(
            game_found=game_path is not None,
            game_path=str(game_path) if game_path else None,
            game_running=self._steam.is_game_running(),
            installed=installed_version is not None,
            installed_version=installed_version,
        )

    def check_latest(self) -> LatestRelease:
        release = self._releases.latest()
        game_path = self._steam.find_game()
        installed = self._installer.installed_version(game_path) if game_path else None
        return LatestRelease(
            version=release.version,
            update_available=(
                installed is not None
                and normalize_version(installed) != release.version
            ),
        )

    def install(self, progress: ProgressReporter) -> PluginStatus:
        with self._mutation_lock:
            game_path = self._preflight(
                "未找到 Steam 版《The Bazaar》。请先安装并启动一次游戏。"
            )
            progress("读取官方发布信息", 5)
            release = self._releases.latest()
            self._installer.install(
                release,
                game_path,
                self._runtime_dir,
                progress,
            )
            return self.status()

    def uninstall(self) -> PluginStatus:
        with self._mutation_lock:
            game_path = self._preflight("未找到 Steam 版《The Bazaar》。")
            self._installer.uninstall(game_path)
            return self.status()

    def reset_data(self) -> PluginStatus:
        with self._mutation_lock:
            game_path = self._preflight("未找到 Steam 版《The Bazaar》。")
            self._installer.reset_data(game_path)
            return self.status()

    def _preflight(self, not_found_message: str) -> Path:
        game_path = self._steam.find_game()
        if game_path is None:
            raise RuntimeError(not_found_message)
        if self._steam.is_game_running():
            raise RuntimeError("《The Bazaar》仍在运行，请先退出游戏。")
        return game_path

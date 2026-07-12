from pathlib import Path

from backend.bpp.models import Release


class FakeSteamEnvironment:
    def __init__(self, game_path: Path | None = None, running: bool = False) -> None:
        self.game_path = game_path
        self.running = running

    def find_game(self) -> Path | None:
        return self.game_path

    def is_game_running(self) -> bool:
        return self.running


class FakeReleaseSource:
    def __init__(self, release: Release) -> None:
        self.release = release
        self.latest_calls = 0

    def latest(self) -> Release:
        self.latest_calls += 1
        return self.release

    def acquire_payload(self, release, working_dir, progress):
        raise AssertionError("application tests use a fake installer")


class FakeInstaller:
    def __init__(self, installed_version: str | None = None) -> None:
        self.version = installed_version
        self.calls: list[tuple[str, Path]] = []

    def install(self, release, game_path, runtime_dir, progress):
        self.calls.append(("install", game_path))
        self.version = release.version
        progress("安装完成", 100)

    def uninstall(self, game_path):
        self.calls.append(("uninstall", game_path))
        self.version = None

    def reset_data(self, game_path):
        self.calls.append(("reset_data", game_path))

    def installed_version(self, game_path):
        return self.version

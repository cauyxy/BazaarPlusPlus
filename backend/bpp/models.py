from dataclasses import dataclass


@dataclass(frozen=True)
class Release:
    version: str
    installer_url: str


@dataclass(frozen=True)
class PluginStatus:
    game_found: bool
    game_path: str | None
    game_running: bool
    installed: bool
    installed_version: str | None


@dataclass(frozen=True)
class LatestRelease:
    version: str
    update_available: bool


def normalize_version(version: str) -> str:
    if version.casefold().endswith(".prod"):
        return version[:-5]
    return version

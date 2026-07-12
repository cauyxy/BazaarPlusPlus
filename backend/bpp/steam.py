import re
from pathlib import Path
from typing import Protocol


APP_ID = 1617400
GAME_DIRECTORY = "The Bazaar"
GAME_EXECUTABLE = "TheBazaar.exe"


class SteamEnvironment(Protocol):
    def find_game(self) -> Path | None: ...

    def is_game_running(self) -> bool: ...


def parse_vdf_paths(contents: str) -> list[Path]:
    paths: list[Path] = []
    for raw in re.findall(r'"path"\s*"((?:\\.|[^"])*)"', contents, re.IGNORECASE):
        decoded = raw.replace("\\\\", "\\")
        candidate = Path(decoded)
        if candidate not in paths:
            paths.append(candidate)
    return paths


def _steam_roots(user_home: Path) -> list[Path]:
    roots = [
        user_home / ".local/share/Steam",
        user_home / ".steam/steam",
        user_home / ".steam/root",
    ]
    discovered: list[Path] = []
    for root in roots:
        if root.exists() and root not in discovered:
            discovered.append(root)
        vdf = root / "steamapps/libraryfolders.vdf"
        try:
            for library in parse_vdf_paths(vdf.read_text("utf-8", errors="replace")):
                if library not in discovered:
                    discovered.append(library)
        except OSError:
            pass

    media_root = Path("/run/media") / user_home.name
    if media_root.is_dir():
        for steamapps in media_root.glob("*/steamapps"):
            library = steamapps.parent
            if library not in discovered:
                discovered.append(library)
    return discovered


def _manifest_install_dir(manifest: Path) -> str | None:
    try:
        contents = manifest.read_text("utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r'"installdir"\s*"([^"]+)"', contents, re.IGNORECASE)
    return match.group(1) if match else None


class LinuxSteamEnvironment:
    def __init__(self, user_home: Path, proc_root: Path = Path("/proc")) -> None:
        self._user_home = user_home
        self._proc_root = proc_root

    def find_game(self) -> Path | None:
        for root in _steam_roots(self._user_home):
            steamapps = root / "steamapps"
            install_dir = _manifest_install_dir(
                steamapps / f"appmanifest_{APP_ID}.acf"
            )
            candidates: list[Path] = []
            if install_dir:
                candidates.append(steamapps / "common" / install_dir)
            candidates.append(steamapps / "common" / GAME_DIRECTORY)
            for candidate in candidates:
                if (candidate / GAME_EXECUTABLE).is_file():
                    return candidate.resolve()
        return None

    def is_game_running(self) -> bool:
        if not self._proc_root.is_dir():
            return False
        for process in self._proc_root.iterdir():
            if not process.name.isdigit():
                continue
            for filename in ("comm", "cmdline"):
                try:
                    text = (process / filename).read_bytes().replace(b"\0", b" ").decode(
                        "utf-8", errors="ignore"
                    )
                except OSError:
                    continue
                if GAME_EXECUTABLE.casefold() in text.casefold():
                    return True
        return False

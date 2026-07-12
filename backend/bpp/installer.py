import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable

from .models import Release, normalize_version
from .release import ProgressReporter, ReleaseSource


DATA_DIRECTORY = "BazaarPlusPlusV4"
MAX_EXTRACTED_BYTES = 400 * 1024 * 1024
BPP_CONFIG = "BepInEx/config/BazaarPlusPlus.cfg"
BPP_PRIVATE_PATHS = (
    BPP_CONFIG,
    "BepInEx/plugins/BazaarPlusPlus.dll",
    "BepInEx/plugins/BazaarPlusPlus.version",
    "BepInEx/plugins/BazaarPlusPlus.ModApi.dll",
    "BepInEx/plugins/BazaarPlusPlus.Storage.dll",
    "BepInEx/plugins/BazaarPlusPlus.Localization.dll",
)
BPP_DEPENDENCY_PATHS = (
    "BepInEx/plugins/Microsoft.Data.Sqlite.dll",
    "BepInEx/plugins/SQLitePCLRaw.batteries_v2.dll",
    "BepInEx/plugins/SQLitePCLRaw.core.dll",
    "BepInEx/plugins/SQLitePCLRaw.provider.e_sqlite3.dll",
    "BepInEx/plugins/SixLabors.ImageSharp.dll",
    "BepInEx/plugins/System.Buffers.dll",
    "BepInEx/plugins/System.Memory.dll",
    "BepInEx/plugins/System.Numerics.Vectors.dll",
    "BepInEx/plugins/System.Text.Encoding.CodePages.dll",
    "BepInEx/plugins/e_sqlite3.dll",
    "BepInEx/plugins/ffmpeg.exe",
    "BepInEx/plugins/ffmpeg-LICENSE.txt",
)


def _safe_zip_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    total = 0
    for member in archive.infolist():
        path = PurePosixPath(member.filename.replace("\\", "/"))
        mode = member.external_attr >> 16
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or stat.S_ISLNK(mode)
        ):
            raise RuntimeError(f"payload 包含不安全路径：{member.filename}")
        total += member.file_size
        if total > MAX_EXTRACTED_BYTES:
            raise RuntimeError("payload 解压后超过安全大小限制")
        members.append(member)
    return members


def _extract_payload(payload_zip: Path, staging: Path, expected_version: str) -> None:
    with zipfile.ZipFile(payload_zip) as archive:
        members = _safe_zip_members(archive)
        archive.extractall(staging, members)
    required = (
        staging / "winhttp.dll",
        staging / "doorstop_config.ini",
        staging / "BepInEx/plugins/BazaarPlusPlus.dll",
        staging / "BepInEx/plugins/BazaarPlusPlus.version",
    )
    if not all(path.is_file() for path in required):
        raise RuntimeError("安装 payload 缺少 Steam Deck 所需文件")
    version_file = staging / "BepInEx/plugins/BazaarPlusPlus.version"
    try:
        payload_version = version_file.read_text("utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise RuntimeError("安装 payload 版本文件无效") from error
    if not payload_version:
        raise RuntimeError("安装 payload 版本为空")
    if normalize_version(payload_version) != expected_version:
        raise RuntimeError(
            f"安装 payload 版本不匹配：预期 {expected_version}，实际 {payload_version}"
        )


def _relative_files(root: Path) -> list[Path]:
    return sorted(
        (path.relative_to(root) for path in root.rglob("*") if path.is_file()),
        key=lambda value: value.as_posix(),
    )


def _assert_safe_destination(game_path: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"拒绝写入不安全路径：{relative}")
    current = game_path
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise RuntimeError(f"拒绝写入符号链接目录：{current}")
    return game_path / relative


def _apply_staged_payload(staging: Path, game_path: Path) -> None:
    files = [
        relative
        for relative in _relative_files(staging)
        if relative.as_posix() != BPP_CONFIG
        or not (game_path / relative).exists()
    ]
    staged = {path.as_posix() for path in files}
    stale = [
        Path(path)
        for path in (*BPP_PRIVATE_PATHS, *BPP_DEPENDENCY_PATHS)
        if path != BPP_CONFIG and path not in staged
    ]
    touched = list(dict.fromkeys([*files, *stale]))
    with tempfile.TemporaryDirectory(prefix="bpp-backup-") as backup_name:
        backup = Path(backup_name)
        existing: set[str] = set()
        for relative in touched:
            destination = _assert_safe_destination(game_path, relative)
            if destination.is_file():
                existing.add(relative.as_posix())
                backup_file = backup / relative
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup_file)
        try:
            for relative in stale:
                _assert_safe_destination(game_path, relative).unlink(missing_ok=True)
            for relative in files:
                source = staging / relative
                destination = _assert_safe_destination(game_path, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + ".bpp-new")
                temporary.unlink(missing_ok=True)
                shutil.copy2(source, temporary)
                os.replace(temporary, destination)
        except Exception as install_error:
            rollback_error: Exception | None = None
            for relative in files:
                destination = _assert_safe_destination(game_path, relative)
                temporary = destination.with_name(destination.name + ".bpp-new")
                try:
                    temporary.unlink(missing_ok=True)
                except Exception as error:
                    rollback_error = error
            for relative in reversed(touched):
                destination = _assert_safe_destination(game_path, relative)
                backup_file = backup / relative
                try:
                    if relative.as_posix() in existing:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup_file, destination)
                    else:
                        destination.unlink(missing_ok=True)
                except Exception as error:
                    rollback_error = error
            if rollback_error is not None:
                raise rollback_error from install_error
            raise


def _third_party_plugins(game_path: Path) -> bool:
    plugins = game_path / "BepInEx/plugins"
    if not plugins.is_dir():
        return False
    owned = {
        Path(path).name.casefold()
        for path in (*BPP_PRIVATE_PATHS, *BPP_DEPENDENCY_PATHS)
    }
    owned.add(".gitkeep")
    return any(child.name.casefold() not in owned for child in plugins.iterdir())


def _remove_paths(game_path: Path, paths: Iterable[str]) -> None:
    for relative_text in paths:
        destination = _assert_safe_destination(game_path, Path(relative_text))
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink(missing_ok=True)
    for relative_text in ("BepInEx/config", "BepInEx/plugins", "BepInEx"):
        directory = game_path / relative_text
        try:
            directory.rmdir()
        except OSError:
            pass


class Installer:
    def __init__(self, releases: ReleaseSource) -> None:
        self._releases = releases

    def install(
        self,
        release: Release,
        game_path: Path,
        runtime_dir: Path,
        progress: ProgressReporter,
    ) -> None:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="bpp-install-", dir=runtime_dir
        ) as temporary_name:
            temporary = Path(temporary_name)
            payload = self._releases.acquire_payload(release, temporary, progress)
            staging = temporary / "staging"
            staging.mkdir()
            progress("校验安装内容", 82)
            _extract_payload(payload, staging, release.version)
            progress("写入游戏目录", 90)
            _apply_staged_payload(staging, game_path)
        progress("安装完成", 100)

    def uninstall(self, game_path: Path) -> None:
        paths = list(BPP_PRIVATE_PATHS)
        if not _third_party_plugins(game_path):
            paths.extend(BPP_DEPENDENCY_PATHS)
        _remove_paths(game_path, paths)

    def reset_data(self, game_path: Path) -> None:
        data_path = game_path / DATA_DIRECTORY
        if data_path.is_symlink():
            raise RuntimeError("拒绝删除符号链接形式的数据目录")
        shutil.rmtree(data_path, ignore_errors=True)

    def installed_version(self, game_path: Path) -> str | None:
        version_file = game_path / "BepInEx/plugins/BazaarPlusPlus.version"
        plugin_file = game_path / "BepInEx/plugins/BazaarPlusPlus.dll"
        if not plugin_file.is_file():
            return None
        try:
            version = version_file.read_text("utf-8").strip()
            return version or "未知"
        except OSError:
            return "未知"

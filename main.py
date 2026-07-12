from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import ssl
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

import decky


APP_ID = 1617400
GAME_DIRECTORY = "The Bazaar"
GAME_EXECUTABLE = "TheBazaar.exe"
DATA_DIRECTORY = "BazaarPlusPlusV4"
RELEASE_MANIFEST_URL = "https://bppinstaller.bazaarplusplus.com/latest.json"
RELEASE_HOST = "bppinstaller.bazaarplusplus.com"
RELEASE_PLATFORM = "windows-x86_64"
SEVENZIP_URL = (
    "https://github.com/ip7z/7zip/releases/download/26.02/"
    "7z2602-linux-x64.tar.xz"
)
SEVENZIP_SHA256 = "41aaba7b1235304ab5aa0624530c67ae829496cd29e875925271efdccc28c03e"
USER_AGENT = "BazaarPlusPlusForSteamDeck/0.1"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
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


def _ssl_context() -> ssl.SSLContext:
    defaults = ssl.get_default_verify_paths()
    if defaults.cafile and Path(defaults.cafile).is_file():
        return ssl.create_default_context()
    for candidate in (
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/ssl/cert.pem",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ):
        if Path(candidate).is_file():
            return ssl.create_default_context(cafile=candidate)
    return ssl.create_default_context()


def _validated_https_url(url: str, allowed_host: str) -> urllib.parse.SplitResult:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise RuntimeError("官方发布 URL 无效") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != allowed_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("官方发布 URL 无效")
    return parsed


def _validated_release_url(url: str) -> urllib.parse.SplitResult:
    return _validated_https_url(url, RELEASE_HOST)


def _validate_manifest_url(url: str) -> None:
    parsed = _validated_release_url(url)
    if parsed.path != "/latest.json":
        raise RuntimeError("官方发布 manifest URL 无效")


def _is_valid_release_version(version: str) -> bool:
    return re.fullmatch(r"[0-9][0-9A-Za-z.+-]{0,63}", version) is not None


def _normalize_version(version: str) -> str:
    if version.casefold().endswith(".prod"):
        return version[:-5]
    return version


def _validate_and_get_installer_version(
    url: str, expected_version: str | None = None
) -> str:
    parsed = _validated_release_url(url)
    try:
        decoded_path = urllib.parse.unquote(parsed.path, errors="strict")
    except UnicodeDecodeError as error:
        raise RuntimeError("官方 Windows 安装器 URL 无效") from error
    parts = decoded_path.split("/")
    path_version = parts[1] if len(parts) > 1 else ""
    if (
        len(parts) != 5
        or parts[0] != ""
        or not _is_valid_release_version(path_version)
        or (expected_version is not None and path_version != expected_version)
        or parts[2] != RELEASE_PLATFORM
        or parts[3] != "updater"
        or any(part in (".", "..") for part in parts[1:])
        or not parts[4].endswith(".exe")
        or not parts[4][:-4]
    ):
        raise RuntimeError("官方 Windows 安装器 URL 无效")
    return path_version


def _request_json(url: str) -> dict[str, Any]:
    _validate_manifest_url(url)
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(
        request, timeout=30, context=_ssl_context()
    ) as response:
        if response.status != 200:
            raise RuntimeError(f"服务器返回 HTTP {response.status}")
        _validate_manifest_url(response.geturl())
        data = response.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            raise RuntimeError("发布 manifest 超过安全大小限制")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise RuntimeError("发布信息格式无效")
    return value


def _latest_release() -> dict[str, str]:
    release = _request_json(RELEASE_MANIFEST_URL)
    raw_version = release.get("version")
    version = raw_version.strip() if isinstance(raw_version, str) else ""
    if not _is_valid_release_version(version):
        raise RuntimeError("官方发布信息缺少有效版本")

    platforms = release.get("platforms")
    if not isinstance(platforms, dict):
        raise RuntimeError("官方发布信息缺少平台列表")
    windows = platforms.get(RELEASE_PLATFORM)
    if not isinstance(windows, dict):
        raise RuntimeError("最新版未提供 Windows x86_64 安装器")
    url = windows.get("url")
    if not isinstance(url, str):
        raise RuntimeError("官方发布信息缺少 Windows 安装器 URL")
    _validate_and_get_installer_version(url, version)

    return {"version": version, "url": url}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(
    url: str,
    destination: Path,
    *,
    expected_sha256: str | None = None,
    allowed_host: str | None = None,
    progress: Callable[[int], None] | None = None,
) -> Path:
    if expected_sha256 is None and allowed_host is None:
        raise RuntimeError("下载必须提供 SHA-256 或受信任来源")
    if (
        expected_sha256 is not None
        and destination.is_file()
        and _sha256(destination) == expected_sha256
    ):
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    downloaded = 0

    try:
        installer_version = None
        if allowed_host == RELEASE_HOST:
            installer_version = _validate_and_get_installer_version(url)
        elif allowed_host is not None:
            _validated_https_url(url, allowed_host)
        with urllib.request.urlopen(
            request, timeout=60, context=_ssl_context()
        ) as response:
            if installer_version is not None:
                _validate_and_get_installer_version(
                    response.geturl(), installer_version
                )
            elif allowed_host is not None:
                _validated_https_url(response.geturl(), allowed_host)
            raw_content_length = response.headers.get("Content-Length")
            try:
                content_length = (
                    int(raw_content_length) if raw_content_length is not None else None
                )
            except (TypeError, ValueError) as error:
                raise RuntimeError("下载文件 Content-Length 无效") from error
            if content_length is not None and (
                content_length < 0 or content_length > MAX_DOWNLOAD_BYTES
            ):
                raise RuntimeError("下载文件超过安全大小限制")
            with temporary.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError("下载文件超过安全大小限制")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress and content_length and content_length > 0:
                        progress(min(100, downloaded * 100 // content_length))
        if content_length is not None and downloaded != content_length:
            raise RuntimeError(
                f"下载大小不匹配：Content-Length {content_length}，实际 {downloaded}"
            )
        if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
            raise RuntimeError("下载文件 SHA-256 校验失败")
        os.replace(temporary, destination)
        return destination
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _ensure_7zz(runtime_dir: Path) -> Path:
    executable = runtime_dir / "tools" / "7zz"
    if executable.is_file() and os.access(executable, os.X_OK):
        return executable

    archive = _download(
        SEVENZIP_URL,
        runtime_dir / "cache" / "7z2602-linux-x64.tar.xz",
        expected_sha256=SEVENZIP_SHA256,
    )
    executable.parent.mkdir(parents=True, exist_ok=True)
    temporary = executable.with_suffix(".part")
    temporary.unlink(missing_ok=True)

    with tarfile.open(archive, "r:xz") as package:
        member = package.getmember("7zz")
        source = package.extractfile(member)
        if source is None or not member.isfile():
            raise RuntimeError("7-Zip 工具包缺少 7zz")
        with temporary.open("wb") as output:
            shutil.copyfileobj(source, output)

    temporary.chmod(0o755)
    os.replace(temporary, executable)
    return executable


def _parse_vdf_paths(contents: str) -> list[Path]:
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
            for library in _parse_vdf_paths(vdf.read_text("utf-8", errors="replace")):
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


def find_game_path(user_home: Path | None = None) -> Path | None:
    home = user_home or Path(decky.DECKY_USER_HOME)
    for root in _steam_roots(home):
        steamapps = root / "steamapps"
        install_dir = _manifest_install_dir(
            steamapps / f"appmanifest_{APP_ID}.acf"
        )
        candidates = []
        if install_dir:
            candidates.append(steamapps / "common" / install_dir)
        candidates.append(steamapps / "common" / GAME_DIRECTORY)
        for candidate in candidates:
            if (candidate / GAME_EXECUTABLE).is_file():
                return candidate.resolve()
    return None


def is_game_running() -> bool:
    proc = Path("/proc")
    if not proc.is_dir():
        return False
    for process in proc.iterdir():
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
    normalized_version = _normalize_version(payload_version)
    if normalized_version != expected_version:
        raise RuntimeError(
            f"安装 payload 版本不匹配：预期 {expected_version}，实际 {payload_version}"
        )


def _extract_installer(executable: Path, installer: Path, destination: Path) -> Path:
    result = subprocess.run(
        [
            str(executable),
            "x",
            "-y",
            f"-o{destination}",
            str(installer),
            "BepInExSource/BepInEx.zip",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"无法提取官方安装包：{result.stdout[-800:]}")
    payload = destination / "BepInExSource/BepInEx.zip"
    if not payload.is_file():
        raise RuntimeError("官方安装包中未找到 BepInEx payload")
    return payload


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
    files = _relative_files(staging)
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
        except Exception:
            for relative in reversed(touched):
                destination = _assert_safe_destination(game_path, relative)
                backup_file = backup / relative
                if relative.as_posix() in existing:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_file, destination)
                else:
                    destination.unlink(missing_ok=True)
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


def _installed_version(game_path: Path) -> str | None:
    version_file = game_path / "BepInEx/plugins/BazaarPlusPlus.version"
    plugin_file = game_path / "BepInEx/plugins/BazaarPlusPlus.dll"
    if not plugin_file.is_file():
        return None
    try:
        version = version_file.read_text("utf-8").strip()
        return version or "未知"
    except OSError:
        return "未知"


def _update_available(latest_version: str) -> bool:
    game_path = find_game_path()
    installed = _installed_version(game_path) if game_path else None
    if installed is None:
        return False
    return _normalize_version(installed) != latest_version


def _status() -> dict[str, Any]:
    game_path = find_game_path()
    installed_version = _installed_version(game_path) if game_path else None
    return {
        "game_found": game_path is not None,
        "game_path": str(game_path) if game_path else None,
        "game_running": is_game_running(),
        "installed": installed_version is not None,
        "installed_version": installed_version,
    }


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    os.replace(temporary, path)


class Plugin:
    async def _main(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.operation_lock = asyncio.Lock()
        self.runtime_dir = Path(decky.DECKY_PLUGIN_RUNTIME_DIR)
        self.settings_dir = Path(decky.DECKY_PLUGIN_SETTINGS_DIR)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.release_cache: tuple[float, dict[str, str]] | None = None
        decky.logger.info("BazaarPlusPlus Steam Deck plugin loaded")

    async def _unload(self) -> None:
        decky.logger.info("BazaarPlusPlus Steam Deck plugin unloaded")

    async def get_status(self) -> dict[str, Any]:
        return await asyncio.to_thread(_status)

    async def check_latest(self) -> dict[str, Any]:
        release = await self._get_release()
        update_available = await asyncio.to_thread(
            _update_available, release["version"]
        )
        return {"version": release["version"], "update_available": update_available}

    async def _get_release(self) -> dict[str, str]:
        if self.release_cache and time.monotonic() - self.release_cache[0] < 600:
            return self.release_cache[1]
        release = await asyncio.to_thread(_latest_release)
        self.release_cache = (time.monotonic(), release)
        return release

    async def _progress(self, message: str, percent: int) -> None:
        await decky.emit("install_progress", message, percent)

    async def install_latest(self) -> dict[str, Any]:
        async with self.operation_lock:
            game_path = await asyncio.to_thread(find_game_path)
            if not game_path:
                raise RuntimeError(
                    "未找到 Steam 版《The Bazaar》。请先安装并启动一次游戏。"
                )
            if await asyncio.to_thread(is_game_running):
                raise RuntimeError("《The Bazaar》仍在运行，请先退出游戏。")

            await self._progress("读取官方发布信息", 5)
            release = await self._get_release()
            await self._progress("准备安全解包工具", 12)
            sevenzip = await asyncio.to_thread(_ensure_7zz, self.runtime_dir)

            def download_progress(value: int) -> None:
                percent = 15 + value * 55 // 100
                asyncio.run_coroutine_threadsafe(
                    self._progress("下载官方安装包", percent), self.loop
                )

            with tempfile.TemporaryDirectory(
                prefix="bpp-install-", dir=self.runtime_dir
            ) as temporary_name:
                temporary = Path(temporary_name)
                installer = temporary / "BazaarPlusPlus-installer.exe"
                await self._progress("下载官方安装包", 15)
                await asyncio.to_thread(
                    _download,
                    release["url"],
                    installer,
                    allowed_host=RELEASE_HOST,
                    progress=download_progress,
                )
                await self._progress("提取 BepInEx payload", 74)
                payload = await asyncio.to_thread(
                    _extract_installer, sevenzip, installer, temporary
                )
                staging = temporary / "staging"
                staging.mkdir()
                await self._progress("校验安装内容", 82)
                await asyncio.to_thread(
                    _extract_payload, payload, staging, release["version"]
                )
                await self._progress("写入游戏目录", 90)
                await asyncio.to_thread(_apply_staged_payload, staging, game_path)

            await self._progress("安装完成", 100)
            result = await asyncio.to_thread(_status)
            decky.logger.info(
                "Installed BazaarPlusPlus %s to %s", release["version"], game_path
            )
            return result

    async def uninstall_mod(self) -> dict[str, Any]:
        async with self.operation_lock:
            game_path = await asyncio.to_thread(find_game_path)
            if not game_path:
                raise RuntimeError("未找到 Steam 版《The Bazaar》。")
            if await asyncio.to_thread(is_game_running):
                raise RuntimeError("《The Bazaar》仍在运行，请先退出游戏。")
            remove_dependencies = not await asyncio.to_thread(
                _third_party_plugins, game_path
            )
            paths = list(BPP_PRIVATE_PATHS)
            if remove_dependencies:
                paths.extend(BPP_DEPENDENCY_PATHS)
            await asyncio.to_thread(_remove_paths, game_path, paths)
            decky.logger.info("Uninstalled BazaarPlusPlus from %s", game_path)
            return await asyncio.to_thread(_status)

    async def reset_data(self) -> dict[str, Any]:
        async with self.operation_lock:
            game_path = await asyncio.to_thread(find_game_path)
            if not game_path:
                raise RuntimeError("未找到 Steam 版《The Bazaar》。")
            if await asyncio.to_thread(is_game_running):
                raise RuntimeError("《The Bazaar》仍在运行，请先退出游戏。")
            data_path = game_path / DATA_DIRECTORY
            if data_path.is_symlink():
                raise RuntimeError("拒绝删除符号链接形式的数据目录")
            await asyncio.to_thread(shutil.rmtree, data_path, True)
            decky.logger.info("Reset BazaarPlusPlus data at %s", data_path)
            return await asyncio.to_thread(_status)

    async def remember_launch_options(self, original: str, managed: str) -> None:
        if len(original) > 16384 or len(managed) > 16384:
            raise RuntimeError("Steam 启动参数过长")
        await asyncio.to_thread(
            _write_json_atomic,
            self.settings_dir / "launch-options.json",
            {"original": original, "managed": managed},
        )

    async def get_launch_options_backup(self) -> dict[str, str] | None:
        path = self.settings_dir / "launch-options.json"
        try:
            value = await asyncio.to_thread(
                json.loads, path.read_text("utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            return None
        original = value.get("original")
        managed = value.get("managed")
        if isinstance(original, str) and isinstance(managed, str):
            return {"original": original, "managed": managed}
        return None

    async def clear_launch_options_backup(self) -> None:
        (self.settings_dir / "launch-options.json").unlink(missing_ok=True)

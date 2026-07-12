import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import tarfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Protocol

from .models import Release


RELEASE_MANIFEST_URL = "https://bppinstaller.bazaarplusplus.com/latest.json"
RELEASE_HOST = "bppinstaller.bazaarplusplus.com"
RELEASE_PLATFORM = "windows-x86_64"
SEVENZIP_URL = (
    "https://github.com/ip7z/7zip/releases/download/26.02/"
    "7z2602-linux-x64.tar.xz"
)
SEVENZIP_SHA256 = "41aaba7b1235304ab5aa0624530c67ae829496cd29e875925271efdccc28c03e"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
CACHE_TTL_SECONDS = 600

ProgressReporter = Callable[[str, int], None]


class ReleaseSource(Protocol):
    def latest(self) -> Release: ...

    def acquire_payload(
        self,
        release: Release,
        working_dir: Path,
        progress: ProgressReporter,
    ) -> Path: ...


def _package_version() -> str:
    try:
        package_json = Path(__file__).parents[2] / "package.json"
        value = json.loads(package_json.read_text("utf-8"))
        version = value.get("version") if isinstance(value, dict) else None
        if isinstance(version, str) and version:
            return version
    except (OSError, json.JSONDecodeError):
        pass
    return "0.2.0"


USER_AGENT = f"BazaarPlusPlusForSteamDeck/{_package_version()}"


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


def _validate_installer_url(url: str, expected_version: str) -> None:
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
        or path_version != expected_version
        or parts[2] != RELEASE_PLATFORM
        or parts[3] != "updater"
        or any(part in (".", "..") for part in parts[1:])
        or not parts[4].endswith(".exe")
        or not parts[4][:-4]
    ):
        raise RuntimeError("官方 Windows 安装器 URL 无效")


def _installer_url_verifier(expected_version: str) -> Callable[[str], None]:
    def verify(url: str) -> None:
        _validate_installer_url(url, expected_version)

    return verify


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


def _parse_release_manifest(value: dict[str, Any]) -> Release:
    raw_version = value.get("version")
    version = raw_version.strip() if isinstance(raw_version, str) else ""
    if not _is_valid_release_version(version):
        raise RuntimeError("官方发布信息缺少有效版本")
    platforms = value.get("platforms")
    if not isinstance(platforms, dict):
        raise RuntimeError("官方发布信息缺少平台列表")
    windows = platforms.get(RELEASE_PLATFORM)
    if not isinstance(windows, dict):
        raise RuntimeError("最新版未提供 Windows x86_64 安装器")
    url = windows.get("url")
    if not isinstance(url, str):
        raise RuntimeError("官方发布信息缺少 Windows 安装器 URL")
    _validate_installer_url(url, version)
    return Release(version=version, installer_url=url)


def _latest_release() -> Release:
    return _parse_release_manifest(_request_json(RELEASE_MANIFEST_URL))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_https_no_credentials(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None:
        raise RuntimeError("下载 URL 必须是不含凭据的 https")


def _download(
    url: str,
    destination: Path,
    *,
    expected_sha256: str | None = None,
    verify_url: Callable[[str], None] | None = None,
    progress: Callable[[int], None] | None = None,
) -> Path:
    if (expected_sha256 is None) == (verify_url is None):
        raise RuntimeError("下载必须提供 SHA-256 或 URL 校验器（二选一）")
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
        if verify_url is not None:
            _assert_https_no_credentials(url)
            verify_url(url)
        with urllib.request.urlopen(
            request, timeout=60, context=_ssl_context()
        ) as response:
            if verify_url is not None:
                final_url = response.geturl()
                _assert_https_no_credentials(final_url)
                verify_url(final_url)
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


class OfficialReleaseSource:
    def __init__(
        self,
        runtime_dir: Path,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._runtime_dir = runtime_dir
        self._clock = clock
        self._cache: tuple[float, Release] | None = None

    def latest(self) -> Release:
        now = self._clock()
        if self._cache and now - self._cache[0] < CACHE_TTL_SECONDS:
            return self._cache[1]
        release = _latest_release()
        self._cache = (self._clock(), release)
        return release

    def acquire_payload(
        self,
        release: Release,
        working_dir: Path,
        progress: ProgressReporter,
    ) -> Path:
        progress("准备安全解包工具", 12)
        sevenzip = _ensure_7zz(self._runtime_dir)
        installer = working_dir / "BazaarPlusPlus-installer.exe"
        progress("下载官方安装包", 15)

        def download_progress(value: int) -> None:
            progress("下载官方安装包", 15 + value * 55 // 100)

        _download(
            release.installer_url,
            installer,
            verify_url=_installer_url_verifier(release.version),
            progress=download_progress,
        )
        progress("提取 BepInEx payload", 74)
        return _extract_installer(sevenzip, installer, working_dir)

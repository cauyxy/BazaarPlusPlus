import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.bpp import release
from backend.bpp.models import Release


INSTALLER_URL = (
    "https://bppinstaller.bazaarplusplus.com/4.4.3/"
    "windows-x86_64/updater/BazaarPlusPlus_4.4.3_x64-setup.exe"
)


class FakeResponse:
    def __init__(self, body=b"", *, url, status=200, headers=None):
        self._body = io.BytesIO(body)
        self._url = url
        self.status = status
        self.headers = headers or {}
        self.read_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def geturl(self):
        return self._url

    def read(self, size=-1):
        self.read_calls += 1
        return self._body.read(size)


class ReleaseSourceTests(unittest.TestCase):
    def test_parses_windows_release(self):
        self.assertEqual(
            release._parse_release_manifest(
                {
                    "version": "4.4.3",
                    "platforms": {"windows-x86_64": {"url": INSTALLER_URL}},
                }
            ),
            Release(version="4.4.3", installer_url=INSTALLER_URL),
        )

    def test_rejects_untrusted_installer_urls(self):
        for url in (
            "http://bppinstaller.bazaarplusplus.com/4.4.3/windows-x86_64/updater/a.exe",
            "https://evil.example/4.4.3/windows-x86_64/updater/a.exe",
            "https://user@bppinstaller.bazaarplusplus.com/4.4.3/windows-x86_64/updater/a.exe",
            "https://bppinstaller.bazaarplusplus.com:8443/4.4.3/windows-x86_64/updater/a.exe",
            "https://bppinstaller.bazaarplusplus.com/4.4.3/linux-x86_64/updater/a.exe",
            "https://bppinstaller.bazaarplusplus.com/4.4.3/windows-x86_64/installer/a.exe",
            "https://bppinstaller.bazaarplusplus.com/4.4.3/windows-x86_64/updater/a.zip",
            "https://bppinstaller.bazaarplusplus.com/4.4.3/windows-x86_64/updater/a.exe?x=1",
            "https://bppinstaller.bazaarplusplus.com/4.4.3/windows-x86_64/updater/a.exe#x",
            "https://bppinstaller.bazaarplusplus.com/9.9.9/windows-x86_64/updater/a.exe",
            "https://bppinstaller.bazaarplusplus.com/4.4.3/windows-x86_64/updater/extra/a.exe",
        ):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                release._validate_installer_url(url, "4.4.3")

    def test_latest_cache_uses_injected_clock(self):
        now = [100.0]
        source = release.OfficialReleaseSource(Path("/runtime"), clock=lambda: now[0])
        first = Release("4.4.3", INSTALLER_URL)
        second = Release("4.4.4", INSTALLER_URL.replace("4.4.3", "4.4.4"))
        with mock.patch.object(
            release, "_latest_release", side_effect=[first, second]
        ) as latest:
            self.assertEqual(source.latest(), first)
            now[0] += 599
            self.assertEqual(source.latest(), first)
            now[0] += 1
            self.assertEqual(source.latest(), second)
        self.assertEqual(latest.call_count, 2)

    def test_user_agent_uses_package_version(self):
        self.assertEqual(release.USER_AGENT, "BazaarPlusPlusForSteamDeck/0.2.0")

    def test_rejects_missing_or_invalid_manifest_fields(self):
        valid = {
            "version": "4.4.3",
            "platforms": {"windows-x86_64": {"url": INSTALLER_URL}},
        }
        invalid = [
            {},
            {**valid, "version": "v4.4.3"},
            {**valid, "version": ""},
            {**valid, "version": 443},
            {"version": "4.4.3"},
            {"version": "4.4.3", "platforms": {"linux-x86_64": {}}},
            {"version": "4.4.3", "platforms": {"windows-x86_64": {}}},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                release._parse_release_manifest(value)


class ManifestRequestTests(unittest.TestCase):
    def test_requests_json_and_accepts_trusted_response(self):
        response = FakeResponse(
            b'{"version":"4.4.3"}', url=release.RELEASE_MANIFEST_URL
        )

        def open_request(request, **kwargs):
            self.assertEqual(request.get_header("Accept"), "application/json")
            self.assertEqual(request.get_header("User-agent"), release.USER_AGENT)
            return response

        with mock.patch.object(release.urllib.request, "urlopen", open_request):
            self.assertEqual(
                release._request_json(release.RELEASE_MANIFEST_URL)["version"],
                "4.4.3",
            )

    def test_rejects_redirect_before_reading_body(self):
        response = FakeResponse(b"{}", url="https://evil.example/latest.json")
        with mock.patch.object(
            release.urllib.request, "urlopen", return_value=response
        ), self.assertRaises(RuntimeError):
            release._request_json(release.RELEASE_MANIFEST_URL)
        self.assertEqual(response.read_calls, 0)

    def test_rejects_oversize_and_non_object_manifest(self):
        response = FakeResponse(b"12345", url=release.RELEASE_MANIFEST_URL)
        with mock.patch.object(release, "MAX_MANIFEST_BYTES", 4), mock.patch.object(
            release.urllib.request, "urlopen", return_value=response
        ), self.assertRaisesRegex(RuntimeError, "安全大小限制"):
            release._request_json(release.RELEASE_MANIFEST_URL)
        response = FakeResponse(b"[]", url=release.RELEASE_MANIFEST_URL)
        with mock.patch.object(
            release.urllib.request, "urlopen", return_value=response
        ), self.assertRaisesRegex(RuntimeError, "格式无效"):
            release._request_json(release.RELEASE_MANIFEST_URL)


class DownloadTests(unittest.TestCase):
    def _download(self, response, **changes):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        destination = Path(temporary.name) / "installer.exe"
        kwargs = {
            "verify_url": release._installer_url_verifier("4.4.3"),
            **changes,
        }
        with mock.patch.object(
            release.urllib.request, "urlopen", return_value=response
        ):
            result = release._download(INSTALLER_URL, destination, **kwargs)
        return result, destination

    def test_downloads_when_initial_and_final_urls_are_trusted(self):
        response = FakeResponse(
            b"payload", url=INSTALLER_URL, headers={"Content-Length": "7"}
        )
        _, destination = self._download(response)
        self.assertEqual(destination.read_bytes(), b"payload")

    def test_rejects_redirects_before_reading_body(self):
        for final_url in (
            "https://evil.example/a.exe",
            INSTALLER_URL.replace("4.4.3", "9.9.9"),
            INSTALLER_URL.replace("updater", "installer"),
            INSTALLER_URL.replace(".exe", ".zip"),
        ):
            with self.subTest(final_url=final_url):
                response = FakeResponse(b"payload", url=final_url)
                with self.assertRaises(RuntimeError):
                    self._download(response)
                self.assertEqual(response.read_calls, 0)

    def test_rejects_invalid_or_oversize_content_length_before_reading(self):
        for length in ("invalid", "-1", str(release.MAX_DOWNLOAD_BYTES + 1)):
            with self.subTest(length=length):
                response = FakeResponse(
                    b"", url=INSTALLER_URL, headers={"Content-Length": length}
                )
                with self.assertRaises(RuntimeError):
                    self._download(response)
                self.assertEqual(response.read_calls, 0)

    def test_rejects_stream_over_limit_and_removes_partial(self):
        response = FakeResponse(b"12345", url=INSTALLER_URL)
        with tempfile.TemporaryDirectory() as root_name, mock.patch.object(
            release, "MAX_DOWNLOAD_BYTES", 4
        ), mock.patch.object(
            release.urllib.request, "urlopen", return_value=response
        ):
            destination = Path(root_name) / "installer.exe"
            with self.assertRaisesRegex(RuntimeError, "安全大小限制"):
                release._download(
                    INSTALLER_URL,
                    destination,
                    verify_url=release._installer_url_verifier("4.4.3"),
                )
            self.assertFalse((Path(root_name) / "installer.exe.part").exists())

    def test_rejects_content_length_mismatch(self):
        response = FakeResponse(
            b"short", url=INSTALLER_URL, headers={"Content-Length": "6"}
        )
        with self.assertRaisesRegex(RuntimeError, "下载大小不匹配"):
            self._download(response)

    def test_url_trust_mode_does_not_reuse_existing_file(self):
        response = FakeResponse(b"new", url=INSTALLER_URL)
        with tempfile.TemporaryDirectory() as root_name, mock.patch.object(
            release.urllib.request, "urlopen", return_value=response
        ):
            destination = Path(root_name) / "installer.exe"
            destination.write_bytes(b"old")
            release._download(
                INSTALLER_URL,
                destination,
                verify_url=release._installer_url_verifier("4.4.3"),
            )
            self.assertEqual(destination.read_bytes(), b"new")

    def test_sha_mode_reuses_matching_cache_and_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as root_name:
            destination = Path(root_name) / "archive.tar.xz"
            destination.write_bytes(b"cached")
            digest = release._sha256(destination)
            with mock.patch.object(release.urllib.request, "urlopen") as urlopen:
                self.assertEqual(
                    release._download(
                        "https://example.com/archive.tar.xz",
                        destination,
                        expected_sha256=digest,
                    ),
                    destination,
                )
            urlopen.assert_not_called()
            response = FakeResponse(b"changed", url="https://example.com/archive.tar.xz")
            with mock.patch.object(
                release.urllib.request, "urlopen", return_value=response
            ), self.assertRaisesRegex(RuntimeError, "SHA-256"):
                release._download(
                    "https://example.com/archive.tar.xz",
                    destination,
                    expected_sha256="0" * 64,
                )

    def test_requires_exactly_one_trust_strategy_and_https(self):
        with tempfile.TemporaryDirectory() as root_name:
            destination = Path(root_name) / "file"
            with self.assertRaisesRegex(RuntimeError, "二选一"):
                release._download(INSTALLER_URL, destination)
            with self.assertRaisesRegex(RuntimeError, "二选一"):
                release._download(
                    INSTALLER_URL,
                    destination,
                    expected_sha256="unused",
                    verify_url=lambda url: None,
                )
            with mock.patch.object(release.urllib.request, "urlopen") as urlopen:
                with self.assertRaisesRegex(RuntimeError, "必须是不含凭据的 https"):
                    release._download(
                        "http://example.com/a.exe",
                        destination,
                        verify_url=lambda url: None,
                    )
            urlopen.assert_not_called()

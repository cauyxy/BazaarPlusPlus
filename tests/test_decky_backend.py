import importlib.util
import io
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock


decky_stub = types.ModuleType("decky")
decky_stub.DECKY_USER_HOME = "/home/deck"
decky_stub.DECKY_PLUGIN_RUNTIME_DIR = "/tmp/bpp-runtime"
decky_stub.DECKY_PLUGIN_SETTINGS_DIR = "/tmp/bpp-settings"
decky_stub.logger = types.SimpleNamespace(info=lambda *args, **kwargs: None)


async def emit(*args):
    return None


decky_stub.emit = emit
sys.modules.setdefault("decky", decky_stub)

spec = importlib.util.spec_from_file_location(
    "bpp_decky_backend", Path(__file__).parents[1] / "main.py"
)
backend = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(backend)


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


class SteamDiscoveryTests(unittest.TestCase):
    def test_parse_vdf_paths_supports_escaped_backslashes(self):
        contents = r'''
        "libraryfolders"
        {
          "0" { "path" "/home/deck/.local/share/Steam" }
          "1" { "path" "D:\\SteamLibrary" }
        }
        '''
        self.assertEqual(
            backend._parse_vdf_paths(contents),
            [Path("/home/deck/.local/share/Steam"), Path(r"D:\SteamLibrary")],
        )

    def test_finds_game_from_library_manifest(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            home = root / "home/deck"
            steam = home / ".local/share/Steam"
            library = root / "sdcard"
            (steam / "steamapps").mkdir(parents=True)
            (steam / "steamapps/libraryfolders.vdf").write_text(
                f'"libraryfolders" {{ "1" {{ "path" "{library}" }} }}',
                "utf-8",
            )
            (library / "steamapps").mkdir(parents=True)
            (
                library / f"steamapps/appmanifest_{backend.APP_ID}.acf"
            ).write_text('"AppState" { "installdir" "Custom Bazaar" }', "utf-8")
            game = library / "steamapps/common/Custom Bazaar"
            game.mkdir(parents=True)
            (game / backend.GAME_EXECUTABLE).write_bytes(b"MZ")

            self.assertEqual(backend.find_game_path(home), game.resolve())


class ArchiveSafetyTests(unittest.TestCase):
    def _archive(self, entries):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, contents in entries:
                archive.writestr(name, contents)
        buffer.seek(0)
        return zipfile.ZipFile(buffer)

    def test_rejects_parent_traversal(self):
        with self._archive([("../outside", b"bad")]) as archive:
            with self.assertRaisesRegex(RuntimeError, "不安全路径"):
                backend._safe_zip_members(archive)

    def test_accepts_expected_payload_paths(self):
        entries = [
            ("winhttp.dll", b"dll"),
            ("doorstop_config.ini", b"config"),
            ("BepInEx/plugins/BazaarPlusPlus.dll", b"plugin"),
            ("BepInEx/plugins/BazaarPlusPlus.version", b"1.2.3"),
        ]
        with tempfile.TemporaryDirectory() as root_name:
            archive_path = Path(root_name) / "payload.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                for name, contents in entries:
                    archive.writestr(name, contents)
            staging = Path(root_name) / "staging"
            staging.mkdir()

            backend._extract_payload(archive_path, staging, "1.2.3")

            self.assertEqual(
                (staging / "BepInEx/plugins/BazaarPlusPlus.version").read_text(),
                "1.2.3",
            )


class PayloadVersionTests(unittest.TestCase):
    def _extract(self, payload_version, expected_version):
        entries = [
            ("winhttp.dll", b"dll"),
            ("doorstop_config.ini", b"config"),
            ("BepInEx/plugins/BazaarPlusPlus.dll", b"plugin"),
            ("BepInEx/plugins/BazaarPlusPlus.version", payload_version),
        ]
        with tempfile.TemporaryDirectory() as root_name:
            archive_path = Path(root_name) / "payload.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                for name, contents in entries:
                    archive.writestr(name, contents)
            staging = Path(root_name) / "staging"
            staging.mkdir()
            backend._extract_payload(archive_path, staging, expected_version)

    def test_accepts_exact_manifest_version(self):
        self._extract(b"1.2.3", "1.2.3")

    def test_accepts_prod_suffix_case_insensitively(self):
        for payload_version in (b"1.2.3.prod", b"1.2.3.PrOd"):
            with self.subTest(payload_version=payload_version):
                self._extract(payload_version, "1.2.3")

    def test_rejects_mismatched_version(self):
        with self.assertRaises(RuntimeError):
            self._extract(b"1.2.4", "1.2.3")

    def test_rejects_empty_version(self):
        with self.assertRaises(RuntimeError):
            self._extract(b"  \n", "1.2.3")

    def test_rejects_invalid_utf8_version(self):
        with self.assertRaises(RuntimeError):
            self._extract(b"1.2.3\xff", "1.2.3")


class ReleaseMetadataTests(unittest.TestCase):
    def _manifest(self, **changes):
        fixture = {
            "version": "4.4.3",
            "notes": "notes",
            "platforms": {
                "linux-x86_64": {"url": "https://example.com/linux.tar.gz"},
                "windows-x86_64": {
                    "url": (
                        "https://bppinstaller.bazaarplusplus.com/4.4.3/"
                        "windows-x86_64/updater/BazaarPlusPlus_4.4.3_x64-setup.exe"
                    ),
                    "signature": "not-used",
                },
            },
        }
        fixture.update(changes)
        return fixture

    def test_selects_windows_platform_from_r2_manifest(self):
        fixture = self._manifest()
        with mock.patch.object(backend, "_request_json", return_value=fixture):
            release = backend._latest_release()

        self.assertEqual(
            release,
            {
                "version": "4.4.3",
                "notes": "notes",
                "url": (
                    "https://bppinstaller.bazaarplusplus.com/4.4.3/"
                    "windows-x86_64/updater/BazaarPlusPlus_4.4.3_x64-setup.exe"
                ),
            },
        )

    def test_missing_or_non_string_notes_become_empty(self):
        missing_notes = self._manifest()
        missing_notes.pop("notes")
        for fixture in (self._manifest(notes=None), missing_notes):
            with self.subTest(fixture=fixture):
                with mock.patch.object(backend, "_request_json", return_value=fixture):
                    self.assertEqual(backend._latest_release()["notes"], "")

    def test_rejects_missing_platforms(self):
        fixture = self._manifest()
        fixture.pop("platforms")
        with mock.patch.object(backend, "_request_json", return_value=fixture):
            with self.assertRaises(RuntimeError):
                backend._latest_release()

    def test_rejects_missing_windows_platform(self):
        fixture = self._manifest(platforms={"linux-x86_64": {}})
        with mock.patch.object(backend, "_request_json", return_value=fixture):
            with self.assertRaises(RuntimeError):
                backend._latest_release()

    def test_rejects_invalid_version(self):
        for version in ("v4.4.3", "", 443):
            with self.subTest(version=version):
                with mock.patch.object(
                    backend,
                    "_request_json",
                    return_value=self._manifest(version=version),
                ):
                    with self.assertRaises(RuntimeError):
                        backend._latest_release()

    def test_rejects_insecure_or_external_installer_url(self):
        for url in (
            "http://bppinstaller.bazaarplusplus.com/4.4.3/windows-x86_64/updater/a.exe",
            "https://evil.example/4.4.3/windows-x86_64/updater/a.exe",
        ):
            with self.subTest(url=url):
                fixture = self._manifest(
                    platforms={backend.RELEASE_PLATFORM: {"url": url}}
                )
                with mock.patch.object(backend, "_request_json", return_value=fixture):
                    with self.assertRaises(RuntimeError):
                        backend._latest_release()

    def test_rejects_installer_url_with_credentials_or_nonstandard_port(self):
        for url in (
            "https://user@bppinstaller.bazaarplusplus.com/4.4.3/windows-x86_64/updater/a.exe",
            "https://bppinstaller.bazaarplusplus.com:8443/4.4.3/windows-x86_64/updater/a.exe",
        ):
            with self.subTest(url=url):
                fixture = self._manifest(
                    platforms={backend.RELEASE_PLATFORM: {"url": url}}
                )
                with mock.patch.object(backend, "_request_json", return_value=fixture):
                    with self.assertRaises(RuntimeError):
                        backend._latest_release()

    def test_rejects_wrong_installer_path_or_platform(self):
        for path in (
            "/4.4.3/windows-x86_64/installer/a.exe",
            "/4.4.3/linux-x86_64/updater/a.exe",
            "/4.4.3/windows-x86_64/updater/extra/a.exe",
            "/4.4.3/windows-x86_64/updater/../a.exe",
        ):
            with self.subTest(path=path):
                fixture = self._manifest(
                    platforms={
                        backend.RELEASE_PLATFORM: {
                            "url": f"https://bppinstaller.bazaarplusplus.com{path}"
                        }
                    }
                )
                with mock.patch.object(backend, "_request_json", return_value=fixture):
                    with self.assertRaises(RuntimeError):
                        backend._latest_release()

    def test_rejects_non_executable_installer_url(self):
        fixture = self._manifest(
            platforms={
                backend.RELEASE_PLATFORM: {
                    "url": (
                        "https://bppinstaller.bazaarplusplus.com/4.4.3/"
                        "windows-x86_64/updater/BazaarPlusPlus.zip"
                    )
                }
            }
        )
        with mock.patch.object(backend, "_request_json", return_value=fixture):
            with self.assertRaises(RuntimeError):
                backend._latest_release()


class ManifestRequestTests(unittest.TestCase):
    def test_requests_json_and_accepts_r2_response(self):
        response = FakeResponse(
            b'{"version":"4.4.3"}', url=backend.RELEASE_MANIFEST_URL
        )

        def open_request(request, **kwargs):
            self.assertEqual(request.get_header("Accept"), "application/json")
            return response

        with mock.patch.object(backend.urllib.request, "urlopen", open_request):
            manifest = backend._request_json(backend.RELEASE_MANIFEST_URL)

        self.assertEqual(manifest["version"], "4.4.3")

    def test_rejects_manifest_redirect_before_reading_body(self):
        response = FakeResponse(b"{}", url="https://evil.example/latest.json")
        with mock.patch.object(backend.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(RuntimeError):
                backend._request_json(backend.RELEASE_MANIFEST_URL)

        self.assertEqual(response.read_calls, 0)

    def test_rejects_manifest_larger_than_limit(self):
        response = FakeResponse(b"12345", url=backend.RELEASE_MANIFEST_URL)
        with (
            mock.patch.object(backend, "MAX_MANIFEST_BYTES", 4),
            mock.patch.object(backend.urllib.request, "urlopen", return_value=response),
        ):
            with self.assertRaises(RuntimeError):
                backend._request_json(backend.RELEASE_MANIFEST_URL)

    def test_rejects_non_object_manifest(self):
        response = FakeResponse(b"[]", url=backend.RELEASE_MANIFEST_URL)
        with mock.patch.object(backend.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(RuntimeError):
                backend._request_json(backend.RELEASE_MANIFEST_URL)


class DownloadTests(unittest.TestCase):
    url = (
        "https://bppinstaller.bazaarplusplus.com/4.4.3/"
        "windows-x86_64/updater/BazaarPlusPlus_4.4.3_x64-setup.exe"
    )

    def test_download_succeeds_when_final_response_stays_on_r2(self):
        response = FakeResponse(
            b"payload",
            url=self.url,
            headers={"Content-Length": "7"},
        )
        with tempfile.TemporaryDirectory() as root_name:
            destination = Path(root_name) / "installer.exe"
            with mock.patch.object(
                backend.urllib.request, "urlopen", return_value=response
            ):
                result = backend._download(
                    self.url, destination, allowed_host=backend.RELEASE_HOST
                )

            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), b"payload")

    def test_rejects_external_redirect_before_reading_body(self):
        response = FakeResponse(b"payload", url="https://evil.example/installer.exe")
        with tempfile.TemporaryDirectory() as root_name:
            destination = Path(root_name) / "installer.exe"
            with mock.patch.object(
                backend.urllib.request, "urlopen", return_value=response
            ):
                with self.assertRaises(RuntimeError):
                    backend._download(
                        self.url, destination, allowed_host=backend.RELEASE_HOST
                    )

        self.assertEqual(response.read_calls, 0)

    def test_rejects_invalid_r2_redirect_before_reading_body(self):
        for final_url in (
            "https://bppinstaller.bazaarplusplus.com/9.9.9/windows-x86_64/updater/a.exe",
            "https://bppinstaller.bazaarplusplus.com/4.4.3/windows-x86_64/installer/a.exe",
            "https://bppinstaller.bazaarplusplus.com/4.4.3/windows-x86_64/updater/a.zip",
        ):
            with self.subTest(final_url=final_url):
                response = FakeResponse(b"payload", url=final_url)
                with tempfile.TemporaryDirectory() as root_name:
                    destination = Path(root_name) / "installer.exe"
                    with mock.patch.object(
                        backend.urllib.request, "urlopen", return_value=response
                    ):
                        with self.assertRaises(RuntimeError):
                            backend._download(
                                self.url,
                                destination,
                                allowed_host=backend.RELEASE_HOST,
                            )

                self.assertEqual(response.read_calls, 0)

    def test_rejects_content_length_over_limit_before_reading(self):
        response = FakeResponse(
            b"",
            url=self.url,
            headers={"Content-Length": str(backend.MAX_DOWNLOAD_BYTES + 1)},
        )
        with tempfile.TemporaryDirectory() as root_name:
            with mock.patch.object(
                backend.urllib.request, "urlopen", return_value=response
            ):
                with self.assertRaises(RuntimeError):
                    backend._download(
                        self.url,
                        Path(root_name) / "installer.exe",
                        allowed_host=backend.RELEASE_HOST,
                    )

        self.assertEqual(response.read_calls, 0)

    def test_rejects_stream_larger_than_limit(self):
        response = FakeResponse(b"12345", url=self.url)
        with tempfile.TemporaryDirectory() as root_name:
            with (
                mock.patch.object(backend, "MAX_DOWNLOAD_BYTES", 4),
                mock.patch.object(
                    backend.urllib.request, "urlopen", return_value=response
                ),
            ):
                with self.assertRaises(RuntimeError):
                    backend._download(
                        self.url,
                        Path(root_name) / "installer.exe",
                        allowed_host=backend.RELEASE_HOST,
                    )

    def test_rejects_content_length_that_does_not_match_body(self):
        response = FakeResponse(
            b"short",
            url=self.url,
            headers={"Content-Length": "6"},
        )
        with tempfile.TemporaryDirectory() as root_name:
            with mock.patch.object(
                backend.urllib.request, "urlopen", return_value=response
            ):
                with self.assertRaises(RuntimeError):
                    backend._download(
                        self.url,
                        Path(root_name) / "installer.exe",
                        allowed_host=backend.RELEASE_HOST,
                    )

    def test_host_restricted_download_does_not_reuse_existing_file(self):
        response = FakeResponse(b"new", url=self.url)
        with tempfile.TemporaryDirectory() as root_name:
            destination = Path(root_name) / "installer.exe"
            destination.write_bytes(b"old")
            with mock.patch.object(
                backend.urllib.request, "urlopen", return_value=response
            ):
                backend._download(
                    self.url, destination, allowed_host=backend.RELEASE_HOST
                )

            self.assertEqual(destination.read_bytes(), b"new")

    def test_failure_removes_partial_file(self):
        response = FakeResponse(b"12345", url=self.url)
        with tempfile.TemporaryDirectory() as root_name:
            destination = Path(root_name) / "installer.exe"
            partial = Path(root_name) / "installer.exe.part"
            with (
                mock.patch.object(backend, "MAX_DOWNLOAD_BYTES", 4),
                mock.patch.object(
                    backend.urllib.request, "urlopen", return_value=response
                ),
            ):
                with self.assertRaises(RuntimeError):
                    backend._download(
                        self.url, destination, allowed_host=backend.RELEASE_HOST
                    )

            self.assertFalse(partial.exists())


class InstallTransactionTests(unittest.TestCase):
    def test_install_preserves_config_and_other_plugins(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            game = root / "game"
            staging = root / "staging"
            (game / "BepInEx/config").mkdir(parents=True)
            (game / "BepInEx/plugins").mkdir(parents=True)
            (staging / "BepInEx/plugins").mkdir(parents=True)
            (game / backend.GAME_EXECUTABLE).write_bytes(b"MZ")
            (game / backend.BPP_CONFIG).write_text("saved=true", "utf-8")
            (game / "BepInEx/plugins/OtherMod.dll").write_bytes(b"other")
            (game / "BepInEx/plugins/BazaarPlusPlus.dll").write_bytes(b"old")
            (staging / "BepInEx/plugins/BazaarPlusPlus.dll").write_bytes(b"new")
            (staging / "BepInEx/plugins/BazaarPlusPlus.version").write_text(
                "9.9.9", "utf-8"
            )
            (staging / "winhttp.dll").write_bytes(b"doorstop")
            (staging / "doorstop_config.ini").write_text("enabled=true", "utf-8")

            backend._apply_staged_payload(staging, game)

            self.assertEqual(
                (game / "BepInEx/plugins/BazaarPlusPlus.dll").read_bytes(), b"new"
            )
            self.assertEqual((game / backend.BPP_CONFIG).read_text(), "saved=true")
            self.assertTrue((game / "BepInEx/plugins/OtherMod.dll").is_file())

    def test_plugin_directory_counts_as_third_party(self):
        with tempfile.TemporaryDirectory() as root_name:
            game = Path(root_name)
            (game / "BepInEx/plugins/SomeOtherMod").mkdir(parents=True)

            self.assertTrue(backend._third_party_plugins(game))


if __name__ == "__main__":
    unittest.main()

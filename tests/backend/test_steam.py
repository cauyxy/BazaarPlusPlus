import tempfile
import unittest
from pathlib import Path

from backend.bpp.steam import (
    APP_ID,
    GAME_EXECUTABLE,
    LinuxSteamEnvironment,
    parse_vdf_paths,
)


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
            parse_vdf_paths(contents),
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
            (library / f"steamapps/appmanifest_{APP_ID}.acf").write_text(
                '"AppState" { "installdir" "Custom Bazaar" }', "utf-8"
            )
            game = library / "steamapps/common/Custom Bazaar"
            game.mkdir(parents=True)
            (game / GAME_EXECUTABLE).write_bytes(b"MZ")

            self.assertEqual(LinuxSteamEnvironment(home).find_game(), game.resolve())

    def test_falls_back_to_default_game_directory(self):
        with tempfile.TemporaryDirectory() as root_name:
            home = Path(root_name)
            game = home / ".local/share/Steam/steamapps/common/The Bazaar"
            game.mkdir(parents=True)
            (game / GAME_EXECUTABLE).write_bytes(b"MZ")
            self.assertEqual(LinuxSteamEnvironment(home).find_game(), game.resolve())

    def test_detects_running_game_from_injected_proc_root(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            process = root / "123"
            process.mkdir()
            (process / "comm").write_text("TheBazaar.exe\n", "utf-8")
            self.assertTrue(
                LinuxSteamEnvironment(Path("/unused"), proc_root=root).is_game_running()
            )

    def test_missing_proc_root_is_not_running(self):
        self.assertFalse(
            LinuxSteamEnvironment(
                Path("/unused"), proc_root=Path("/definitely/missing")
            ).is_game_running()
        )

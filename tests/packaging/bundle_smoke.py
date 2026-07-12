import importlib.util
import sys
import tempfile
import types
import zipfile
from pathlib import Path


def main(zip_path: str) -> None:
    archive_path = Path(zip_path)
    with tempfile.TemporaryDirectory(prefix="bpp-bundle-smoke-") as root_name:
        root = Path(root_name)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(root)
        package = root / "BazaarPlusPlus"
        entrypoint = package / "main.py"
        if not entrypoint.is_file():
            raise SystemExit("bundle is missing BazaarPlusPlus/main.py")
        for required in (
            package / "backend/__init__.py",
            package / "backend/bpp/__init__.py",
            package / "backend/bpp/decky_adapter.py",
        ):
            if not required.is_file():
                raise SystemExit(f"bundle is missing {required.relative_to(package)}")

        decky = types.ModuleType("decky")
        decky.DECKY_USER_HOME = str(root / "home")
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(root / "runtime")
        decky.DECKY_PLUGIN_SETTINGS_DIR = str(root / "settings")
        decky.logger = types.SimpleNamespace(info=lambda *args, **kwargs: None)

        async def emit(*args):
            return None

        decky.emit = emit
        sys.modules["decky"] = decky
        sys.path.insert(0, str(package))
        try:
            spec = importlib.util.spec_from_file_location("bpp_bundle_main", entrypoint)
            if spec is None or spec.loader is None:
                raise SystemExit("cannot create bundle main.py import spec")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not isinstance(getattr(module, "Plugin", None), type):
                raise SystemExit("bundle main.py does not expose Plugin")
        finally:
            sys.path.remove(str(package))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: bundle_smoke.py <plugin.zip>")
    main(sys.argv[1])

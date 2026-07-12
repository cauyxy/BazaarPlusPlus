import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]


class ArchitectureRulesTests(unittest.TestCase):
    def test_python_dependency_boundaries(self):
        backend = ROOT / "backend/bpp"
        for path in backend.glob("*.py"):
            source = path.read_text("utf-8")
            tree = ast.parse(source)
            imports = {
                alias.name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            } | {
                (node.module or "").split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            }
            if "decky" in imports:
                self.assertEqual(path.name, "decky_adapter.py")
            if "urllib" in imports:
                self.assertEqual(path.name, "release.py")
            for restricted in ("subprocess", "tarfile", "zipfile"):
                if restricted in imports:
                    self.assertIn(path.name, {"installer.py", "release.py"})

    def test_thin_python_and_typescript_entrypoints(self):
        tree = ast.parse((ROOT / "main.py").read_text("utf-8"))
        self.assertEqual(len(tree.body), 2)
        import_node, export_node = tree.body
        self.assertIsInstance(import_node, ast.ImportFrom)
        self.assertEqual(import_node.module, "backend.bpp.decky_adapter")
        self.assertEqual([alias.name for alias in import_node.names], ["Plugin"])
        self.assertIsInstance(export_node, ast.Assign)
        self.assertEqual(
            [target.id for target in export_node.targets if isinstance(target, ast.Name)],
            ["__all__"],
        )

    def test_app_id_contract_matches_both_runtimes(self):
        tree = ast.parse((ROOT / "backend/bpp/steam.py").read_text("utf-8"))
        assignments = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        self.assertEqual(assignments.get("APP_ID"), 1617400)

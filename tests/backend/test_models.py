import unittest

from backend.bpp.models import normalize_version


class NormalizeVersionTests(unittest.TestCase):
    def test_normalization_contract(self):
        cases = {
            "1.2.3.prod": "1.2.3",
            "1.2.3.PrOd": "1.2.3",
            "1.2.3": "1.2.3",
            "1.2.prod.3": "1.2.prod.3",
            "未知": "未知",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(normalize_version(value), expected)

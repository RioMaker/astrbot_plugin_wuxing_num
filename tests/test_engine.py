import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import calculate, parse_five_digits  # noqa: E402


class EngineTests(unittest.TestCase):
    def test_digit_formats(self):
        self.assertEqual(parse_five_digits("12345"), "12345")
        self.assertEqual(parse_five_digits("1，2 3、4,5"), "12345")

    def test_rejects_not_exactly_five_single_digits(self):
        for value in ("1234", "123456", "1 2 3 45", "abcde"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_five_digits(value)

    def test_success_is_definitive(self):
        result = calculate("出行是否顺利", "13824", "水")
        self.assertEqual(result.verdict, "成")
        self.assertTrue(result.phrase.startswith("成："))

    def test_missing_root_is_dead(self):
        result = calculate("合同能否签成", "12327", "金")
        self.assertEqual(result.verdict, "死卦")
        self.assertEqual(result.dead_reason, "根气不现")

    def test_valid_but_blocked_is_failure(self):
        result = calculate("合同能否签成", "41235", "金")
        self.assertEqual(result.verdict, "败")
        self.assertTrue(result.phrase.startswith("败："))


if __name__ == "__main__":
    unittest.main()

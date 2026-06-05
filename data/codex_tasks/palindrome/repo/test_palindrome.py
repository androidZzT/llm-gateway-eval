import unittest

from palindrome import is_palindrome


class PalindromeTest(unittest.TestCase):
    def test_ignores_case_and_punctuation(self) -> None:
        self.assertTrue(is_palindrome("A man, a plan, a canal: Panama!"))

    def test_negative_case(self) -> None:
        self.assertFalse(is_palindrome("gateway"))

    def test_simple_palindrome(self) -> None:
        self.assertTrue(is_palindrome("RaceCar"))


if __name__ == "__main__":
    unittest.main()


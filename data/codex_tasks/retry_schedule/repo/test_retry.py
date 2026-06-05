import unittest

from retry import retry_delays


class RetryScheduleTest(unittest.TestCase):
    def test_exponential_backoff_with_cap(self) -> None:
        self.assertEqual(retry_delays(5, base=0.5, cap=3.0), [0.5, 1.0, 2.0, 3.0, 3.0])

    def test_deterministic_jitter(self) -> None:
        self.assertEqual(retry_delays(6, base=1.0, cap=10.0, jitter=0.1), [0.9, 2.0, 4.1, 7.9, 10.0, 10.0])

    def test_no_negative_delays(self) -> None:
        self.assertEqual(retry_delays(2, base=0.05, cap=1.0, jitter=0.2), [0.0, 0.1])

    def test_no_retries(self) -> None:
        self.assertEqual(retry_delays(0), [])


if __name__ == "__main__":
    unittest.main()


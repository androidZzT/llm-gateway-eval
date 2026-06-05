import unittest

from events import summarize_events


class EventSummaryTest(unittest.TestCase):
    def test_summarizes_only_active_records(self) -> None:
        raw = "\n".join(
            [
                '{"email":"A@example.com","active":true,"tags":["beta","vip"]}',
                '{"email":"b@example.com","active":false,"tags":["vip"]}',
                '{"email":"c@example.com","active":true,"tags":["beta","new","beta"]}',
                "not-json",
                "",
                '{"email":"a@example.com","active":true,"tags":["vip"]}',
            ]
        )

        self.assertEqual(
            summarize_events(raw),
            {
                "active_count": 3,
                "emails": ["a@example.com", "c@example.com"],
                "tag_counts": {"beta": 3, "new": 1, "vip": 2},
            },
        )

    def test_empty_input(self) -> None:
        self.assertEqual(summarize_events("\n\n"), {"active_count": 0, "emails": [], "tag_counts": {}})


if __name__ == "__main__":
    unittest.main()


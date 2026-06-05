import unittest

from toc import build_toc


class MarkdownTocTest(unittest.TestCase):
    def test_builds_toc_and_ignores_code_fences(self) -> None:
        markdown = """# Title

Text

```python
# Not A Heading
```

## Usage & Setup!
### Usage Setup
## Usage Setup
"""

        self.assertEqual(
            build_toc(markdown),
            [
                {"level": 1, "title": "Title", "slug": "title"},
                {"level": 2, "title": "Usage & Setup!", "slug": "usage-setup"},
                {"level": 3, "title": "Usage Setup", "slug": "usage-setup-2"},
                {"level": 2, "title": "Usage Setup", "slug": "usage-setup-3"},
            ],
        )

    def test_ignores_plain_hash_text(self) -> None:
        self.assertEqual(build_toc("abc # not a heading"), [])


if __name__ == "__main__":
    unittest.main()


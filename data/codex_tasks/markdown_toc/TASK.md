Fix the implementation so all tests pass.

Requirements:
- `build_toc` receives a Markdown string and returns a list of dictionaries.
- Include only ATX headings that start with `#`.
- Ignore headings inside fenced code blocks.
- Return each item as `{"level": int, "title": str, "slug": str}`.
- Slugs should lowercase text, drop punctuation, collapse whitespace/dashes, and add `-2`, `-3`, etc. for duplicates.
- Run `bash ./verify.sh` before finishing.


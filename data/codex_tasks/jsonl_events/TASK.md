Fix the implementation so all tests pass.

Requirements:
- `summarize_events` receives newline-delimited JSON records.
- Ignore blank lines and malformed JSON lines.
- Count only records whose `active` field is true.
- Return lowercase unique emails sorted alphabetically.
- Count tags across active records and return tag counts sorted by tag name.
- Run `bash ./verify.sh` before finishing.


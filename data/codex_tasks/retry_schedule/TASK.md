Fix the implementation so all tests pass.

Requirements:
- `retry_delays` returns retry delays in seconds for attempts after the first request.
- Use exponential backoff: `base * 2 ** index`.
- Apply a maximum cap to each delay.
- Apply deterministic jitter when `jitter` is provided: add `jitter * ((index % 3) - 1)`.
- Never return negative delays.
- Round each delay to 3 decimal places.
- Run `bash ./verify.sh` before finishing.


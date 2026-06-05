def retry_delays(attempts: int, base: float = 0.5, cap: float = 8.0, jitter: float = 0.0) -> list[float]:
    return [base for _ in range(attempts)]


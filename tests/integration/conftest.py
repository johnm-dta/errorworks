"""Shared fixtures and helpers for integration tests."""

# Standard chat completion body for LLM integration tests
CHAT_BODY = {
    "model": "test",
    "messages": [{"role": "user", "content": "hello"}],
}


def assert_rate_near(actual_count: int, total: int, expected_pct: float, tolerance_pct: float = 3.0) -> None:
    """Assert observed rate is within tolerance of expected percentage."""
    actual_pct = (actual_count / total) * 100
    assert abs(actual_pct - expected_pct) <= tolerance_pct, (
        f"Expected ~{expected_pct}%, got {actual_pct}% ({actual_count}/{total})"
    )

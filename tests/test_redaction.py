from llm_gateway_eval.redaction import redact_text


def test_redact_text_removes_common_secrets() -> None:
    redacted = redact_text(
        "key sk-test-secret-123456 email ada@example.com token=abcdef1234567890 Bearer xyz123456789"
    )

    assert "sk-test-secret" not in redacted
    assert "ada@example.com" not in redacted
    assert "abcdef1234567890" not in redacted
    assert "xyz123456789" not in redacted
    assert "[REDACTED_API_KEY]" in redacted


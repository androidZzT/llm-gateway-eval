from llm_gateway_eval.assertions import evaluate_assertion, parse_json_from_output
from llm_gateway_eval.models import AssertionSpec


def test_basic_assertions_pass() -> None:
    assert evaluate_assertion(AssertionSpec(type="contains", value="hello"), "hello world").passed
    assert evaluate_assertion(AssertionSpec(type="not_contains", value="secret"), "public").passed
    assert evaluate_assertion(AssertionSpec(type="equals", value="pong"), " pong\n").passed
    assert evaluate_assertion(AssertionSpec(type="regex", value=r"^ORD-\d+$"), "ORD-123").passed


def test_json_schema_assertion_extracts_fenced_json() -> None:
    result = evaluate_assertion(
        AssertionSpec(
            type="json_schema",
            schema={
                "type": "object",
                "required": ["ok"],
                "properties": {"ok": {"const": True}},
            },
        ),
        "```json\n{\"ok\": true}\n```",
    )

    assert result.passed


def test_json_schema_assertion_fails_cleanly() -> None:
    result = evaluate_assertion(
        AssertionSpec(
            type="json_schema",
            schema={"type": "object", "required": ["ok"]},
        ),
        "{\"nope\": true}",
    )

    assert not result.passed
    assert "required property" in result.message


def test_parse_json_from_output_finds_embedded_object() -> None:
    assert parse_json_from_output("Result: {\"score\": 80}") == {"score": 80}


def test_refusal_expected() -> None:
    result = evaluate_assertion(
        AssertionSpec(type="refusal_expected", value=True),
        "抱歉，我不能帮助完成这个请求。",
    )

    assert result.passed


import json

from llm_gateway_eval.honeytokens import analyze_honeytoken_events, load_honeytoken_event_records


def test_analyze_honeytoken_events_detects_matching_url(tmp_path) -> None:
    probe_payload = {
        "honeytokens": [
            {
                "id": "external_fetch_url",
                "kind": "url",
                "value": "https://webhook.example/hook?honeytoken=egress-test",
            }
        ]
    }
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        json.dumps({"path": "/none"}) + "\n"
        + json.dumps({"url": "https://webhook.example/hook?honeytoken=egress-test"}) + "\n",
        encoding="utf-8",
    )

    records = load_honeytoken_event_records(events_path)
    analysis = analyze_honeytoken_events(probe_payload, records, events_path)

    assert analysis.status == "FAIL"
    assert analysis.matched_event_count == 1
    assert analysis.matches[0]["token_id"] == "external_fetch_url"
    assert "https://webhook.example" not in analysis.matches[0]["event_excerpt"]
    assert "[HONEYTOKEN:external_fetch_url]" in analysis.matches[0]["event_excerpt"]


def test_analyze_honeytoken_events_passes_when_no_match(tmp_path) -> None:
    probe_payload = {
        "honeytokens": [
            {
                "id": "external_fetch_url",
                "kind": "url",
                "value": "https://webhook.example/hook?honeytoken=egress-test",
            }
        ]
    }
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps({"events": [{"url": "https://example.test/other"}]}), encoding="utf-8")

    records = load_honeytoken_event_records(events_path)
    analysis = analyze_honeytoken_events(probe_payload, records, events_path)

    assert analysis.status == "PASS"
    assert analysis.total_records == 1
    assert analysis.matched_event_count == 0

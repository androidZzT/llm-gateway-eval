import json
import os
import time

from llm_gateway_eval.audit import AuditFinding
from llm_gateway_eval.models import AssertionResult, RunResult, Usage
from llm_gateway_eval.web_server import WEB_GATEWAY_API_KEY_PREFIX, WebEvalJobStore, render_index_html


def test_render_index_html_contains_evaluator_controls() -> None:
    html = render_index_html()

    assert "LLM Gateway API 测评站" in html
    assert "gateway_url" in html
    assert "api_key" in html
    assert "开始测评" in html
    assert "/api/jobs" in html


def test_web_job_runs_eval_and_redacts_raw_api_key(tmp_path, monkeypatch) -> None:
    cases_path = tmp_path / "data" / "cases" / "gateway_core.jsonl"
    cases_path.parent.mkdir(parents=True, exist_ok=True)
    cases_path.write_text(
        json.dumps(
            {
                "id": "ping",
                "category": "stability",
                "messages": [{"role": "user", "content": "ping"}],
                "assertions": [{"type": "equals", "value": "pong"}],
                "tags": ["stability"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "llm_gateway_eval.web_server.audit_config",
        lambda config, online_tls: [
            AuditFinding("gateway", "transport_scheme", "PASS", "base_url uses HTTPS", "https")
        ],
    )

    async def fake_run_evaluation(config, cases):
        assert os.getenv(config.targets[0].api_key_env) == "secret-web-key"
        return [
            RunResult(
                case_id="ping",
                category="stability",
                tags=["stability"],
                provider="gateway",
                model="gpt-test",
                output="pong",
                usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2),
                latency_seconds=0.1,
                ttft_seconds=None,
                error=None,
                attempts=1,
                assertion_results=[AssertionResult("equals", True, "ok")],
                cost=0.0,
                currency="CNY",
                requested_model="gpt-test",
            )
        ]

    monkeypatch.setattr("llm_gateway_eval.web_server.run_evaluation", fake_run_evaluation)
    store = WebEvalJobStore(tmp_path)

    job = store.create(
        {
            "gateway_url": "https://gateway.example/v1",
            "model": "gpt-test",
            "api_key": "secret-web-key",
            "categories": ["stability"],
            "dynamic_security_probes": False,
            "online_tls": False,
        }
    )

    deadline = time.time() + 3
    while time.time() < deadline:
        current = store.get(job.id)
        if current and current.status in {"completed", "failed"}:
            break
        time.sleep(0.02)

    current = store.get(job.id)
    assert current is not None
    assert current.status == "completed", current.error
    assert current.summary is not None
    assert current.summary["providers"]["gateway"]["request_success_rate"] == 1
    artifact_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            tmp_path / current.out_dir / "request.json",
            tmp_path / current.out_dir / "quick_config.json",
            tmp_path / current.out_dir / "results.jsonl",
            tmp_path / current.out_dir / "summary.json",
        ]
        if path.exists()
    )
    assert "secret-web-key" not in artifact_text
    assert not any(name.startswith(WEB_GATEWAY_API_KEY_PREFIX) for name in os.environ)

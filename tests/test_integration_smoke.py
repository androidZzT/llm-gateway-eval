import json
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from typer.testing import CliRunner

from llm_gateway_eval.cli import app


class MockOpenAIHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        _ = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": "mock-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "pong"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        }
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args) -> None:  # noqa: A002
        return


def test_cli_run_to_report_with_mock_server(tmp_path, monkeypatch) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}/v1"
    monkeypatch.setenv("MOCK_OPENAI_KEY", "test-key")

    config_path = tmp_path / "eval.yaml"
    config_path.write_text(
        textwrap.dedent(
            f"""
            run:
              timeout_seconds: 5
              concurrency: 1
              repeat_per_case: 2
            targets:
              - name: mock
                base_url: {base_url}
                api_key_env: MOCK_OPENAI_KEY
                model: mock-model
                params:
                  temperature: 0
                pricing:
                  input_per_million: 1
                  output_per_million: 2
            """
        ),
        encoding="utf-8",
    )
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "id": "ping",
                "category": "compatibility",
                "messages": [{"role": "user", "content": "ping"}],
                "assertions": [{"type": "equals", "value": "pong"}],
                "tags": ["smoke"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    run_dir = tmp_path / "run"
    run_result = runner.invoke(
        app,
        ["run", "--config", str(config_path), "--cases", str(cases_path), "--out", str(run_dir)],
    )
    assert run_result.exit_code == 0, run_result.output
    assert (run_dir / "results.jsonl").exists()
    assert (run_dir / "summary.json").exists()
    assert len((run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()) == 2

    report_path = tmp_path / "report.md"
    report_result = runner.invoke(app, ["report", str(run_dir), "--out", str(report_path)])
    assert report_result.exit_code == 0, report_result.output
    assert "Provider Scores" in report_path.read_text(encoding="utf-8")

    server.shutdown()

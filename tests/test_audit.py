from llm_gateway_eval.audit import audit_config
from llm_gateway_eval.models import EvalConfig, ProviderTarget, ReportOptions, RunOptions


def test_audit_fails_non_local_http() -> None:
    config = EvalConfig(
        run=RunOptions(),
        targets=[
            ProviderTarget(
                name="bad",
                base_url="http://gateway.example.com/v1",
                api_key_env="KEY",
                model="model",
            )
        ],
        report=ReportOptions(),
    )

    findings = audit_config(config)

    assert any(finding.check == "transport_scheme" and finding.status == "FAIL" for finding in findings)


def test_audit_allows_local_http_as_warning() -> None:
    config = EvalConfig(
        run=RunOptions(),
        targets=[
            ProviderTarget(
                name="local",
                base_url="http://127.0.0.1:9999/v1",
                api_key_env="KEY",
                model="model",
            )
        ],
        report=ReportOptions(),
    )

    findings = audit_config(config)

    assert any(finding.check == "transport_scheme" and finding.status == "WARN" for finding in findings)


def test_audit_rejects_static_authorization_header() -> None:
    config = EvalConfig(
        run=RunOptions(),
        targets=[
            ProviderTarget(
                name="bad",
                base_url="https://gateway.example.com/v1",
                api_key_env="KEY",
                model="model",
                headers={"Authorization": "Bearer hard-coded-token"},
            )
        ],
        report=ReportOptions(),
    )

    findings = audit_config(config)

    assert any(finding.check == "static_secret_headers" and finding.status == "FAIL" for finding in findings)


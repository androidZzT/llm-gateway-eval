import textwrap

import pytest

from llm_gateway_eval.config import ConfigError, load_config, validate_config_env


def test_load_config_and_validate_env(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "eval.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            targets:
              - name: mock
                base_url: http://127.0.0.1:9999/v1
                api_key_env: MOCK_KEY
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
    monkeypatch.setenv("MOCK_KEY", "test-key")

    config = load_config(config_path)

    assert config.targets[0].name == "mock"
    assert config.targets[0].base_url == "http://127.0.0.1:9999/v1"
    assert config.targets[0].pricing.output_per_million == 2
    validate_config_env(config)


def test_validate_env_reports_missing_key(tmp_path) -> None:
    config_path = tmp_path / "eval.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            targets:
              - name: mock
                base_url: http://127.0.0.1:9999/v1
                api_key_env: MISSING_KEY
                model: mock-model
            """
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    with pytest.raises(ConfigError, match="MISSING_KEY"):
        validate_config_env(config)


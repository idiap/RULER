# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the Azure OpenAI live-demo connection tester."""

from __future__ import annotations

import importlib.util
from ruler.io import read_yaml
from ruler.paths import REPO_ROOT

SCRIPT_PATH = (
    REPO_ROOT
    / "proj_skills"
    / "project-management"
    / "azure-openai-connection-tester"
    / "scripts"
    / "test_azure_openai_connection.py"
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location("azure_connection_tester", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_demo_config_points_to_azure_responses_endpoint() -> None:
    """The live demo config should target Azure OpenAI Responses with no committed key."""
    config = read_yaml(REPO_ROOT / "config" / "generative_connection.yaml")
    genai = config["generative_api"]
    rendered = (REPO_ROOT / "config" / "generative_connection.yaml").read_text(encoding="utf-8")

    assert genai["provider"] == "azure_openai"
    assert (
        genai["endpoint"] == "https://lunarflow-resource.services.ai.azure.com/openai/v1/responses"
    )
    assert genai["model"] == "gpt-5.5"
    assert genai["api_key_env"] == "AZURE_OPENAI_API_KEY"
    assert genai["local_secret_config_path"] == "config/live_mcp_web_demo.local.yaml"
    assert genai["auth_header"] == "api-key"
    assert genai["api_version_query_required"] is False
    assert "key:" not in rendered.lower()


def test_azure_connection_tester_dry_run_is_secret_free(monkeypatch) -> None:
    """Dry-run should validate wiring without requiring or leaking the API key."""
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    public_config = REPO_ROOT / "config" / "generative_connection.yaml"
    module = _load_script_module()
    module.CONFIG_PATH = public_config

    report = module.test_connection(dry_run=True)

    assert report["status"] == "dry_run_ok"
    assert report["model"] == "gpt-5.5"
    assert report["request_payload"]["model"] == "gpt-5.5"
    assert "AZURE_OPENAI_API_KEY" in report["api_key_env"]
    assert "api_key" not in report


def test_azure_connection_tester_reads_gitignored_local_config(tmp_path, monkeypatch) -> None:
    """A local YAML override can carry the key without changing the public config."""
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    public_config = tmp_path / "generative_connection.yaml"
    local_config = tmp_path / "live_mcp_web_demo.local.yaml"
    public_config.write_text(
        "\n".join(
            [
                "server:",
                "  request_limits: {}",
                "generative_api:",
                "  provider: azure_openai",
                "  endpoint: https://example.test/openai/v1/responses",
                "  model: gpt-5.5",
                "  api_key_env: AZURE_OPENAI_API_KEY",
                "  auth_header: api-key",
                "  wire_api: responses",
                "  api_version_query_required: false",
                f"  local_secret_config_path: {local_config}",
            ]
        ),
        encoding="utf-8",
    )
    local_config.write_text("generative_api:\n  api_key: local-secret-value\n", encoding="utf-8")
    module = _load_script_module()
    module.CONFIG_PATH = public_config

    config = module.load_config(public_config)
    report = module.test_connection(dry_run=True)
    explicit_key, explicit_source = module._resolve_api_key(config["generative_api"])

    assert config["generative_api"]["api_key"] == "local-secret-value"
    assert explicit_key == "local-secret-value"
    assert explicit_source == "local_config"
    assert report["api_key_present"] is True
    assert report["api_key_source"] == "local_config"
    assert report["request_payload"]["model"] == "gpt-5.5"

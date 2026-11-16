# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for generative API configuration safety.

These tests make sure RULER defaults to local, non-network generative behavior and
that provider overrides never leak secrets into summaries or validation output.
"""

from __future__ import annotations

from ruler.runtime.api_config import load_generative_api_config, validate_generative_api_config


def test_default_generative_api_config_is_local_and_redacted() -> None:
    """Default config must be safe for offline/local validation runs."""
    config = load_generative_api_config(env={})
    summary = config.redacted_summary(env={})

    assert config.default_provider == "local_stub"
    assert summary["provider"]["allow_network"] is False
    assert summary["provider"]["api_key_present"] is False
    assert "openai" in summary["available_providers"]
    assert "azure_openai" in summary["available_providers"]
    assert validate_generative_api_config() == []


def test_azure_openai_provider_is_configured_without_committed_secret() -> None:
    """Azure Responses API config should point at the deployment and keep key env-only."""
    config = load_generative_api_config(env={})
    provider = config.providers["azure_openai"]

    assert provider.model == "gpt-5.5"
    assert provider.api_key_env == "AZURE_OPENAI_API_KEY"
    assert (
        provider.base_url == "https://lunarflow-resource.services.ai.azure.com/openai/v1/responses"
    )
    assert provider.allow_network is True
    assert provider.enabled is False
    assert provider.redacted(env={})["api_key_present"] is False


def test_env_overrides_select_network_provider_without_exposing_secret() -> None:
    """Environment overrides may select a provider, but summaries stay redacted."""
    env = {
        "RULER_GENAI_PROVIDER": "openai",
        "RULER_GENAI_MODEL": "example-model",
        "RULER_GENAI_API_KEY_ENV": "OPENAI_API_KEY",
        "RULER_GENAI_TEMPERATURE": "0.2",
        "RULER_GENAI_ALLOW_NETWORK": "true",
        "OPENAI_API_KEY": "secret-value",
    }
    config = load_generative_api_config(env=env)
    summary = config.redacted_summary(env=env)

    assert config.default_provider == "openai"
    assert summary["provider"]["model"] == "example-model"
    assert summary["provider"]["api_key_present"] is True
    assert "secret-value" not in str(summary)


def test_workflow_defaults_apply_model_and_sampling_overrides() -> None:
    config = load_generative_api_config(env={})

    explanation = config.selected_provider("explanation")

    assert explanation.provider == "azure_openai"
    assert explanation.model == "gpt-5.5"
    assert explanation.temperature == 0.0

# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Protocol tests for real configured API request/response shapes."""

from __future__ import annotations

import json

import pytest

from ruler.runtime.api_config import GenerativeProviderConfig
from ruler.runtime.generative_transport import (
    ConfiguredApiTransport,
    ConfiguredApiTransportError,
)


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _config(provider: str, base_url: str, key_env: str) -> GenerativeProviderConfig:
    return GenerativeProviderConfig(
        provider=provider,
        model="test-model",
        api_key_env=key_env,
        base_url=base_url,
        enabled=True,
        allow_network=True,
        max_retries=0,
    )


def test_openai_compatible_transport_sends_schema_and_parses_output(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response({"output_text": '{"decision":"retain"}'})

    monkeypatch.setattr("ruler.runtime.generative_transport.urlopen", fake_urlopen)
    transport = ConfiguredApiTransport(
        _config("openai", "https://api.openai.example/v1", "TEST_OPENAI_KEY"),
        env={"TEST_OPENAI_KEY": "secret"},
    )
    schema = {
        "type": "object",
        "properties": {"decision": {"type": "string"}},
        "required": ["decision"],
        "additionalProperties": False,
    }

    assert transport.generate(prompt="Choose.", output_schema=schema) == {"decision": "retain"}
    request = captured["request"]
    assert request.full_url == "https://api.openai.example/v1/responses"
    assert request.get_header("Authorization") == "Bearer secret"
    body = json.loads(request.data)
    assert body["text"]["format"]["schema"] == schema
    assert body["text"]["format"]["strict"] is True


def test_anthropic_transport_uses_forced_structured_tool(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return _Response({"content": [{"type": "tool_use", "input": {"decision": "replace"}}]})

    monkeypatch.setattr("ruler.runtime.generative_transport.urlopen", fake_urlopen)
    transport = ConfiguredApiTransport(
        _config("anthropic", "https://api.anthropic.example", "TEST_ANTHROPIC_KEY"),
        env={"TEST_ANTHROPIC_KEY": "secret"},
    )

    result = transport.generate(
        prompt="Choose.",
        output_schema={"type": "object", "properties": {}},
    )

    assert result == {"decision": "replace"}
    request = captured["request"]
    assert request.full_url == "https://api.anthropic.example/v1/messages"
    assert request.get_header("X-api-key") == "secret"
    assert json.loads(request.data)["tool_choice"]["name"] == "return_structured_result"


def test_azure_openai_transport_uses_api_key_and_exact_responses_endpoint(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return _Response({"output_text": '{"status":"ok"}'})

    monkeypatch.setattr("ruler.runtime.generative_transport.urlopen", fake_urlopen)
    endpoint = "https://azure.example/openai/v1/responses"
    transport = ConfiguredApiTransport(
        _config("azure_openai", endpoint, "TEST_AZURE_KEY"),
        env={"TEST_AZURE_KEY": "secret"},
    )

    assert transport.generate(
        prompt="Report status.",
        output_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
        },
    ) == {"status": "ok"}
    request = captured["request"]
    assert request.full_url == endpoint
    assert request.get_header("Api-key") == "secret"
    assert request.get_header("Authorization") is None


def test_local_stub_and_missing_credentials_fail_closed() -> None:
    with pytest.raises(ConfiguredApiTransportError, match="supported network provider"):
        ConfiguredApiTransport(
            GenerativeProviderConfig(
                provider="local_stub", model="deterministic-noop", enabled=True
            ),
            env={},
        )
    with pytest.raises(ConfiguredApiTransportError, match="credential"):
        ConfiguredApiTransport(
            _config("openai", "https://api.openai.example/v1", "MISSING_KEY"),
            env={},
        )


def test_transport_rejects_provider_output_outside_schema(monkeypatch) -> None:
    monkeypatch.setattr(
        "ruler.runtime.generative_transport.urlopen",
        lambda request, timeout: _Response({"output_text": '{"decision": 4}'}),
    )
    transport = ConfiguredApiTransport(
        _config("openai", "https://api.openai.example/v1", "TEST_OPENAI_KEY"),
        env={"TEST_OPENAI_KEY": "secret"},
    )

    with pytest.raises(ConfiguredApiTransportError, match="does not satisfy"):
        transport.generate(
            prompt="Choose.",
            output_schema={
                "type": "object",
                "properties": {"decision": {"type": "string"}},
                "required": ["decision"],
            },
        )

# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Real HTTP transport for configured structured-generation providers.

The adapter deliberately owns only provider I/O.  Semantic validation and
promotion remain with the deterministic RULER workflows that consume its JSON.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jsonschema import SchemaError, ValidationError, validate

from ruler.runtime.api_config import GenerativeProviderConfig

MAX_PROMPT_CHARS = 64_000
MAX_SCHEMA_BYTES = 128_000
MAX_RESPONSE_BYTES = 4_000_000
SUPPORTED_NETWORK_PROVIDERS = frozenset({"openai", "azure_openai", "anthropic"})


class ConfiguredApiTransportError(RuntimeError):
    """A configured network request could not produce bounded structured JSON."""


class ConfiguredApiTransport:
    """Provider-neutral structured generation over real HTTPS APIs."""

    def __init__(
        self,
        config: GenerativeProviderConfig,
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config
        self.provider = config.provider
        self.model = config.model
        self._env = os.environ if env is None else env
        self._validate_runtime_config()

    def generate(self, *, prompt: str, output_schema: Mapping[str, Any]) -> Mapping[str, Any]:
        """Call the selected provider and return its schema-targeted JSON object."""
        if not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
            raise ConfiguredApiTransportError("prompt must contain 1 to 64000 characters")
        try:
            schema_bytes = json.dumps(output_schema, sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ConfiguredApiTransportError("output schema must be JSON serializable") from exc
        if len(schema_bytes) > MAX_SCHEMA_BYTES:
            raise ConfiguredApiTransportError("output schema exceeds 128000 bytes")

        url, headers, body = self._request(prompt, output_schema)
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                request = Request(url, data=encoded, headers=headers, method="POST")
                with urlopen(
                    request, timeout=self.config.timeout_seconds
                ) as response:  # noqa: S310
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ConfiguredApiTransportError("provider response exceeds 4000000 bytes")
                payload = json.loads(raw.decode("utf-8"))
                value = self._extract(payload)
                if not isinstance(value, dict):
                    raise ConfiguredApiTransportError("provider result must be a JSON object")
                try:
                    validate(instance=value, schema=output_schema)
                except (SchemaError, ValidationError) as exc:
                    raise ConfiguredApiTransportError(
                        "provider result does not satisfy the requested JSON schema"
                    ) from exc
                return value
            except ConfiguredApiTransportError:
                raise
            except (
                HTTPError,
                URLError,
                TimeoutError,
                OSError,
                UnicodeError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(min(0.25 * (2**attempt), 1.0))
        raise ConfiguredApiTransportError(
            f"{self.provider} request failed after {self.config.max_retries + 1} attempt(s)"
        ) from last_error

    def _validate_runtime_config(self) -> None:
        if self.provider not in SUPPORTED_NETWORK_PROVIDERS:
            raise ConfiguredApiTransportError(
                "selected provider is not a supported network provider"
            )
        if not self.config.enabled or not self.config.allow_network:
            raise ConfiguredApiTransportError("selected provider is not enabled for network use")
        if not self.config.base_url or not self.config.base_url.startswith("https://"):
            raise ConfiguredApiTransportError("network provider requires an HTTPS base_url")
        if not self.config.api_key_env or not self._env.get(self.config.api_key_env):
            raise ConfiguredApiTransportError("configured API credential is unavailable")

    def _request(
        self, prompt: str, output_schema: Mapping[str, Any]
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        assert self.config.base_url is not None  # Checked before requests are enabled.
        api_key = self._env[self.config.api_key_env or ""]
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        headers.update(self._extra_headers())
        if self.provider == "anthropic":
            headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
            return (
                self.config.base_url.rstrip("/") + "/v1/messages",
                headers,
                {
                    "model": self.model,
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": [
                        {
                            "name": "return_structured_result",
                            "description": "Return the requested structured RULER result.",
                            "input_schema": output_schema,
                        }
                    ],
                    "tool_choice": {"type": "tool", "name": "return_structured_result"},
                },
            )
        if self.provider == "azure_openai":
            headers["api-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"
        base_url = self.config.base_url.rstrip("/")
        url = base_url if base_url.endswith("/responses") else base_url + "/responses"
        return (
            url,
            headers,
            {
                "model": self.model,
                "input": prompt,
                "temperature": self.config.temperature,
                "max_output_tokens": self.config.max_tokens,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "ruler_result",
                        "strict": True,
                        "schema": output_schema,
                    }
                },
            },
        )

    def _extra_headers(self) -> dict[str, str]:
        env_name = self.config.extra_headers_env
        if not env_name or not self._env.get(env_name):
            return {}
        try:
            value = json.loads(self._env[env_name])
        except json.JSONDecodeError as exc:
            raise ConfiguredApiTransportError("extra headers must be a JSON object") from exc
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in value.items()
        ):
            raise ConfiguredApiTransportError("extra headers must map strings to strings")
        lowered = {key.lower() for key in value}
        if lowered & {"authorization", "api-key", "x-api-key"}:
            raise ConfiguredApiTransportError("extra headers cannot override credentials")
        return value

    def _extract(self, payload: object) -> Mapping[str, Any]:
        if not isinstance(payload, dict):
            raise ConfiguredApiTransportError("provider response must be a JSON object")
        if self.provider == "anthropic":
            for item in payload.get("content", []):
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    value = item.get("input")
                    if isinstance(value, dict):
                        return value
            raise ConfiguredApiTransportError("Anthropic response omitted structured tool input")
        output_text = payload.get("output_text")
        if isinstance(output_text, str):
            return _decode_object(output_text)
        for output in payload.get("output", []):
            if not isinstance(output, dict):
                continue
            for item in output.get("content", []):
                if isinstance(item, dict) and item.get("type") == "output_text":
                    text = item.get("text")
                    if isinstance(text, str):
                        return _decode_object(text)
        raise ConfiguredApiTransportError("OpenAI response omitted structured output text")


def _decode_object(value: str) -> Mapping[str, Any]:
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfiguredApiTransportError("structured output is not valid JSON") from exc
    if not isinstance(result, dict):
        raise ConfiguredApiTransportError("structured output must be a JSON object")
    return result

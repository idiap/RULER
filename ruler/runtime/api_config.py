# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Configuration boundary for generative API use. The concepts here are provider selection,
local-first defaults, environment overrides, and redacted summaries so networked
generation can be enabled without leaking secrets.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ruler.io import read_yaml
from ruler.paths import REFERENCE_DIR

GEN_API_CONFIG_FILE = REFERENCE_DIR / "generative_api_config.yaml"


class GenerativeProviderConfig(BaseModel):
    """One provider profile, including model defaults and secret environment names."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    api_key_env: str | None = None
    base_url: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    max_retries: int = Field(default=2, ge=0, le=10)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=200000)
    enabled: bool = False
    allow_network: bool = False
    extra_headers_env: str | None = None

    def redacted(self, env: Mapping[str, str] | None = None) -> dict[str, Any]:
        """Return provider settings without exposing API keys or header contents."""
        env = os.environ if env is None else env
        key_present = bool(self.api_key_env and env.get(self.api_key_env))
        headers_present = bool(self.extra_headers_env and env.get(self.extra_headers_env))
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "api_key_present": key_present,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "enabled": self.enabled,
            "allow_network": self.allow_network,
            "extra_headers_env": self.extra_headers_env,
            "extra_headers_present": headers_present,
        }


class WorkflowGenerativeDefaults(BaseModel):
    """Workflow-specific generation defaults that can override the provider baseline."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    model: str | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=200000)


class GenerativeApiConfig(BaseModel):
    """Complete generative API configuration loaded from refs and environment overrides."""

    model_config = ConfigDict(extra="forbid")

    default_provider: str
    providers: dict[str, GenerativeProviderConfig]
    workflow_defaults: dict[str, WorkflowGenerativeDefaults] = Field(default_factory=dict)

    def selected_provider(self, workflow: str | None = None) -> GenerativeProviderConfig:
        """Resolve the provider that should serve a workflow or the global default."""
        provider_name = self.default_provider
        if workflow and workflow in self.workflow_defaults:
            provider_name = self.workflow_defaults[workflow].provider
        provider = self.providers[provider_name]
        if workflow and workflow in self.workflow_defaults:
            defaults = self.workflow_defaults[workflow]
            updates: dict[str, Any] = {"temperature": defaults.temperature}
            if defaults.model is not None:
                updates["model"] = defaults.model
            if defaults.max_tokens is not None:
                updates["max_tokens"] = defaults.max_tokens
            provider = provider.model_copy(update=updates)
        return provider

    def redacted_summary(
        self,
        workflow: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Summarize effective generation settings in a log-safe shape."""
        provider = self.selected_provider(workflow)
        return {
            "default_provider": self.default_provider,
            "selected_provider": provider.provider,
            "workflow": workflow,
            "provider": provider.redacted(env=env),
            "available_providers": sorted(self.providers),
            "workflow_defaults": {
                name: default.model_dump(mode="json")
                for name, default in sorted(self.workflow_defaults.items())
            },
        }


def load_generative_api_config(
    path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> GenerativeApiConfig:
    """Load generative API config for the API config workflow."""
    env = os.environ if env is None else env
    config_path = path or Path(env.get("RULER_GENAI_CONFIG", GEN_API_CONFIG_FILE))
    payload = read_yaml(config_path)
    config = GenerativeApiConfig.model_validate(payload)
    return _apply_env_overrides(config, env)


def validate_generative_api_config(path: Path | None = None) -> list[str]:
    """Validate generative API config for the API config workflow."""
    errors: list[str] = []
    try:
        config = load_generative_api_config(path)
    except Exception as exc:
        return [f"invalid generative API config: {exc}"]

    if config.default_provider not in config.providers:
        errors.append(f"default provider {config.default_provider!r} is not declared")
    for name, provider in config.providers.items():
        if name != provider.provider:
            errors.append(f"{name}: provider key must match provider field")
        if provider.allow_network and not provider.api_key_env:
            errors.append(f"{name}: network provider must declare api_key_env")
        if (
            provider.enabled
            and provider.allow_network
            and not os.environ.get(provider.api_key_env or "")
        ):
            errors.append(f"{name}: enabled network provider lacks configured API key env")
        if provider.provider == "local_stub" and provider.allow_network:
            errors.append("local_stub must not allow network")
    for workflow, defaults in config.workflow_defaults.items():
        if defaults.provider not in config.providers:
            errors.append(f"{workflow}: unknown provider {defaults.provider!r}")
    return errors


def _apply_env_overrides(
    config: GenerativeApiConfig,
    env: Mapping[str, str],
) -> GenerativeApiConfig:
    """Internal helper for apply env overrides in the API config workflow."""
    provider_name = env.get("RULER_GENAI_PROVIDER")
    if not provider_name:
        return config
    base = config.providers.get(provider_name)
    if base is None:
        base = GenerativeProviderConfig(
            provider=provider_name,
            model=env.get("RULER_GENAI_MODEL", "configured-by-env"),
            api_key_env=env.get("RULER_GENAI_API_KEY_ENV"),
            base_url=env.get("RULER_GENAI_BASE_URL"),
            enabled=True,
            allow_network=_env_bool(env.get("RULER_GENAI_ALLOW_NETWORK"), default=True),
        )
    overrides: dict[str, Any] = {
        "provider": provider_name,
        "enabled": True,
    }
    _maybe_set(overrides, "model", env.get("RULER_GENAI_MODEL"))
    _maybe_set(overrides, "api_key_env", env.get("RULER_GENAI_API_KEY_ENV"))
    _maybe_set(overrides, "base_url", env.get("RULER_GENAI_BASE_URL"))
    _maybe_set_int(overrides, "timeout_seconds", env.get("RULER_GENAI_TIMEOUT_SECONDS"))
    _maybe_set_int(overrides, "max_retries", env.get("RULER_GENAI_MAX_RETRIES"))
    _maybe_set_float(overrides, "temperature", env.get("RULER_GENAI_TEMPERATURE"))
    _maybe_set_int(overrides, "max_tokens", env.get("RULER_GENAI_MAX_TOKENS"))
    if "RULER_GENAI_ALLOW_NETWORK" in env:
        overrides["allow_network"] = _env_bool(env["RULER_GENAI_ALLOW_NETWORK"], default=False)
    provider = base.model_copy(update=overrides)
    providers = {**config.providers, provider_name: provider}
    return config.model_copy(update={"default_provider": provider_name, "providers": providers})


def _maybe_set(target: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None and value != "":
        target[key] = value


def _maybe_set_int(target: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None and value != "":
        target[key] = int(value)


def _maybe_set_float(target: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None and value != "":
        target[key] = float(value)


def _env_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

# Lunar AI

"""Test RULER's Azure OpenAI Responses endpoint configuration.

The script supports a dry run that validates endpoint/model/key-env wiring without
network access. A live run sends a minimal Responses API request using the Azure
`api-key` header and never prints the secret value.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = ROOT / "config" / "generative_connection.yaml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load the live demo YAML config and its optional local secret override."""
    config_path = path or CONFIG_PATH
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    local_secret_path = _resolve_local_secret_path(config_path, config)
    if local_secret_path and local_secret_path.exists():
        with local_secret_path.open("r", encoding="utf-8") as handle:
            local_config = yaml.safe_load(handle) or {}
        config = _merge_config(config, local_config)
    return config


def build_payload(model: str) -> dict[str, Any]:
    """Build a minimal Responses API health prompt."""
    return {
        "model": model,
        "input": ("Reply with exactly: ruler azure connection ok"),
        "max_output_tokens": 32,
    }


def test_connection(dry_run: bool = False, timeout: int | None = None) -> dict[str, Any]:
    """Run a dry-run or live Azure OpenAI Responses API connection test."""
    config = load_config()
    genai = config["generative_api"]
    endpoint = genai["endpoint"]
    model = genai["model"]
    key_env = genai["api_key_env"]
    header_name = genai["auth_header"]
    api_key, api_key_source = _resolve_api_key(genai)
    payload = build_payload(model)
    report: dict[str, Any] = {
        "provider": genai["provider"],
        "endpoint": endpoint,
        "model": model,
        "api_key_env": key_env,
        "api_key_present": bool(api_key),
        "api_key_source": api_key_source,
        "wire_api": genai["wire_api"],
        "api_version_query_required": genai["api_version_query_required"],
    }
    if dry_run:
        return {**report, "status": "dry_run_ok", "request_payload": payload}
    if not api_key:
        return {
            **report,
            "status": "missing_key",
            "message": (
                f"Set {key_env} or put generative_api.api_key in "
                f"{genai.get('local_secret_config_path')} before live test."
            ),
        }

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            header_name: api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout or int(config["server"]["request_limits"].get("timeout_seconds", 60)),
        ) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw)
            return {
                **report,
                "status": "ok",
                "http_status": response.status,
                "response_id": parsed.get("id"),
                "output_preview": _extract_output_preview(parsed),
            }
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:1000]
        return {
            **report,
            "status": "http_error",
            "http_status": exc.code,
            "error_preview": body_text,
        }
    except urllib.error.URLError as exc:
        return {**report, "status": "url_error", "error": str(exc.reason)}


def _resolve_local_secret_path(config_path: Path, config: dict[str, Any]) -> Path | None:
    """Resolve the optional gitignored secret file declared by the main config."""
    local_secret = config.get("generative_api", {}).get("local_secret_config_path")
    if not local_secret:
        return None
    path = Path(local_secret)
    if not path.is_absolute():
        path = config_path.parent.parent / path
    return path


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge a narrow local YAML override into the public config."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_api_key(genai: dict[str, Any]) -> tuple[str | None, str]:
    """Resolve API key from environment first, then the gitignored local config."""
    key_env = genai["api_key_env"]
    env_key = os.getenv(key_env)
    if env_key:
        return env_key, "env"
    local_key = genai.get("api_key")
    if isinstance(local_key, str) and local_key.strip():
        return local_key.strip(), "local_config"
    return None, "absent"


def _extract_output_preview(payload: dict[str, Any]) -> str | None:
    """Extract a compact text preview from a Responses API payload."""
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"][:240]
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                return text[:240]
    return None


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    report = test_connection(dry_run=args.dry_run, timeout=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] in {"dry_run_ok", "ok"} else 1


if __name__ == "__main__":
    sys.exit(main())

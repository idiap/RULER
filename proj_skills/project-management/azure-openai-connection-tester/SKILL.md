---
name: azure-openai-connection-tester
description: Test the RULER Azure OpenAI Responses endpoint configuration for the live MCP web demo, using gpt-5.5, AZURE_OPENAI_API_KEY, safe dry-runs, and redacted connection reports.
---

# Azure OpenAI Connection Tester

Use this skill when validating that RULER can reach the configured Azure
OpenAI Responses endpoint for live-demo generative functions.

## Endpoint Contract

- Endpoint: `https://lunarflow-resource.services.ai.azure.com/openai/v1/responses`
- Model deployment name: `gpt-5.5`
- Key environment variable: `AZURE_OPENAI_API_KEY`
- Optional local key file: `config/live_mcp_web_demo.local.yaml`
- Wire API: Azure OpenAI v1 Responses API
- Auth header: `api-key`
- No `api-version` query parameter for this v1 endpoint.

## Procedure

1. Dry-run the config without a key:

```bash
uv run python proj_skills/project-management/azure-openai-connection-tester/scripts/test_azure_openai_connection.py --dry-run
```

2. Add the key locally with either an environment variable:

```bash
export AZURE_OPENAI_API_KEY="<your-key>"
```

Or put it in the gitignored local config:

```yaml
generative_api:
  api_key: "<your-key>"
```

3. Run the live connection test:

```bash
uv run python proj_skills/project-management/azure-openai-connection-tester/scripts/test_azure_openai_connection.py
```

## Expected Result

- Dry-run reports `status: dry_run_ok`.
- Live run reports `status: ok` and a response id or output preview.
- Reports never print the API key.

## Failure Triage

- `missing_key`: set `AZURE_OPENAI_API_KEY` or `generative_api.api_key` in
  `config/live_mcp_web_demo.local.yaml`.
- `401` or `403`: key or resource permission issue.
- `404`: endpoint, deployment name, or v1 Responses support issue.
- timeout: network or Azure service reachability issue.

## Validation

```bash
uv run pytest -q tests/project_management/test_azure_openai_connection_tester.py
uv run ruler validate api-config
```

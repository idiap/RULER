<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# RULER product plugin

The Codex and Claude plugin exports exactly four skills:

- `ruler-prepare-knowledge`
- `ruler-prepare-request`
- `ruler-execute-reasoning`
- `ruler-retrieve-results`

Their source is `plugin/skills/`. The internal canonical catalogue in `skills/`
continues to support native CLI workflows and hooks; it is not exported by the
plugin. The old full-catalogue workflow contracts and source snapshots are retired.

Connect the [RULER MCP server](mcp_server.md) to execute the four workflows.
The plugin supplies instructions only: it contains no runtime, database,
credentials, automatic hooks or MCP connection configuration.

## Build and validate

```sh
uv run ruler prepare plugins --refresh-manifests
uv run ruler validate plugins
```

The generated marketplace is `build/ruler/plugins`, with the plugin under
`build/ruler/plugins/ruler`. It includes four flat skill directories, both host
manifests, the portable `plugin.json`, and Idiap research and education licensing metadata. Rebuilding
replaces only a marked generated output directory and removes stale exports.

Use the repository root or generated marketplace as the host's plugin source.
For a local Claude session:

```sh
claude --plugin-dir /absolute/path/to/ruler/build/ruler/plugins/ruler
```

In Claude invoke `/ruler:ruler-prepare-knowledge`, or the matching skill name for
another stage. In Codex select the corresponding RULER product skill. Existing
installations must refresh or reinstall their package to remove old exports.
The MCP server must also restart to advertise its new four-tool surface.

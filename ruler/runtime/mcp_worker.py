# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Private single-invocation worker for database-materialized MCP workspaces.

Never accepts a Python name, shell command, or filesystem path from an MCP caller.
Only operations registered on the fixed internal MCP server can be invoked.
"""

import contextlib
import json
import os
import sys
import time


def main() -> None:
    try:
        request = json.load(sys.stdin)
        with contextlib.redirect_stdout(sys.stderr):
            from ruler.cli import _domain_registry
            from ruler.runtime.mcp_projects import ProjectMCPService
            from ruler.runtime.mcp_server import _create_mcp_server

            projects = ProjectMCPService(_domain_registry, clock=time.time)
            projects.restore_plans(request["plans"])
            operations = {}
            _create_mcp_server(project_service=projects, operations=operations)
            result = operations[request["operation"]](**request["arguments"])
            response = {"ok": True, "result": result, "plans": projects.snapshot_plans()}
        # Temporary absolute paths are never useful outside this invocation.
        root = os.environ["RULER_WORKSPACE_ROOT"]

        def portable(value):
            if isinstance(value, str):
                return value.replace(root + os.sep, "").replace(root, ".")
            if isinstance(value, dict):
                return {key: portable(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [portable(item) for item in value]
            return value

        sys.stdout.write(json.dumps(portable(response)))
    except Exception:
        # Do not forward provider errors, subprocess stderr, credentials, or local paths.
        sys.stdout.write(json.dumps({"ok": False}))
        sys.exit(1)


if __name__ == "__main__":
    main()

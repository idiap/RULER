# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Thin MCP launch script. It delegates to the packaged RULER MCP server entrypoint for
users who prefer a script path over the console command.
"""

from __future__ import annotations

from ruler.runtime.mcp_server import main

if __name__ == "__main__":
    main()

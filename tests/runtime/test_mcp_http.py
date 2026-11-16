# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Remote protocol, origin protection, and per-client import authorization."""

import asyncio
from contextlib import contextmanager
import socket
import threading
import time

from click.testing import CliRunner
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings
import uvicorn

from ruler.cli import main
from ruler.persistence.workspace import PostgresMCPRuntime
from ruler.runtime.mcp_server import create_mcp_http_app, create_mcp_server


@contextmanager
def remote_server(monkeypatch):
    # Exercise the actual SDK transport, replacing only database execution.
    monkeypatch.setattr(
        PostgresMCPRuntime,
        "invoke",
        lambda self, operation, arguments: {
            "session": self.session_id,
            "operation": operation,
        },
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        settings = {
            "host": "127.0.0.1",
            "port": port,
            "json_response": True,
            "stateless_http": False,
            "transport_security": TransportSecuritySettings(
                allowed_hosts=[f"127.0.0.1:{port}"],
                allowed_origins=[],
            ),
        }
        mcp = create_mcp_server(runtime=PostgresMCPRuntime(store=object()), http_settings=settings)
        server = uvicorn.Server(uvicorn.Config(create_mcp_http_app(mcp), log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()


def test_remote_sessions_do_not_share_import_authorization(monkeypatch):
    async def exercise(url):
        async with streamable_http_client(url) as (read1, write1, _):
            async with ClientSession(read1, write1) as first:
                await first.initialize()
                a = (
                    await first.call_tool(
                        "ruler_prepare_knowledge",
                        {
                            "input": {
                                "action": "plan_import",
                                "project_id": "regulatory",
                                "corpus_id": "example",
                            },
                        },
                    )
                ).structuredContent
                async with streamable_http_client(url) as (read2, write2, _):
                    async with ClientSession(read2, write2) as second:
                        await second.initialize()
                        b = (
                            await second.call_tool(
                                "ruler_prepare_knowledge",
                                {
                                    "input": {"action": "apply_import", "plan_id": "example"},
                                    "allow_write": True,
                                },
                            )
                        ).structuredContent
                c = (
                    await first.call_tool(
                        "ruler_prepare_knowledge",
                        {
                            "input": {"action": "apply_import", "plan_id": "example"},
                            "allow_write": True,
                        },
                    )
                ).structuredContent
                assert a["session"] == c["session"]
                assert a["session"] != b["session"]

    with remote_server(monkeypatch) as url:
        asyncio.run(exercise(url))


def test_http_transport_rejects_untrusted_hosts_and_browser_origins(monkeypatch):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    with remote_server(monkeypatch) as url:
        headers = {"Accept": "application/json, text/event-stream"}
        # Idle clients cannot hold a standalone, billable SSE request open.
        response = httpx.get(url, headers=headers)
        assert response.status_code == 405
        assert response.headers["Allow"] == "POST, DELETE"
        assert (
            httpx.post(
                url, json=payload, headers={**headers, "Host": "attacker.example"}
            ).status_code
            == 421
        )
        assert (
            httpx.post(
                url, json=payload, headers={**headers, "Origin": "https://attacker.example"}
            ).status_code
            == 403
        )


def test_cli_keeps_stdio_default_and_honors_cloud_run_port(monkeypatch):
    calls = []
    monkeypatch.setattr("ruler.runtime.mcp_server.main", lambda **kwargs: calls.append(kwargs))
    runner = CliRunner()
    assert runner.invoke(main, ["serve", "mcp"]).exit_code == 0
    assert calls[-1] == {"transport": "stdio", "host": "127.0.0.1", "port": 8080}
    monkeypatch.setenv("PORT", "9090")
    assert (
        runner.invoke(
            main, ["serve", "mcp", "--transport", "streamable-http", "--host", "0.0.0.0"]
        ).exit_code
        == 0
    )
    assert calls[-1] == {"transport": "streamable-http", "host": "0.0.0.0", "port": 9090}

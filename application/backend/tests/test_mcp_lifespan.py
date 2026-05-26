from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_AUTH_HEADERS


@pytest.mark.asyncio
async def test_fastapi_lifespan_enters_mcp_streamable_http_lifespan(monkeypatch):
    from app import main

    events = []

    class FakeRouter:
        @asynccontextmanager
        async def lifespan_context(self, app):
            events.append(("enter", app))
            yield
            events.append(("exit", app))

    class FakeMCPApp:
        router = FakeRouter()

    fake_mcp_app = FakeMCPApp()
    monkeypatch.setattr(main, "mcp_app", fake_mcp_app)

    async with main.lifespan(main.fastapi_app):
        events.append(("inside", None))

    assert events == [
        ("enter", fake_mcp_app),
        ("inside", None),
        ("exit", fake_mcp_app),
    ]


def test_mcp_initialize_endpoint_has_started_session_manager():
    from app.main import app

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "1.0"},
        },
    }
    headers = {
        **TEST_AUTH_HEADERS,
        "Accept": "application/json, text/event-stream",
    }

    with TestClient(app) as client:
        response = client.post("/mcp/", json=payload, headers=headers)

    assert response.status_code != 500
    assert "Task group is not initialized" not in response.text

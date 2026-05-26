import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.admin.api import handle_admin_api
from app.services.debate.models import Debate, DebateStatus, Participant
from tests.conftest import TEST_BOOTSTRAP_KEY


def _admin_scope(path: str, method: str) -> dict:
    return {
        "type": "http",
        "path": path,
        "method": method,
        "headers": [(b"authorization", f"Bearer {TEST_BOOTSTRAP_KEY}".encode())],
    }


async def _call_admin_api(path: str, method: str = "GET", body: dict | None = None):
    messages = []
    raw_body = json.dumps(body or {}).encode()

    async def receive():
        return {"type": "http.request", "body": raw_body, "more_body": False}

    async def send(message):
        messages.append(message)

    await handle_admin_api(_admin_scope(path, method), receive, send, mcp=MagicMock())
    return messages


def _json_response(messages):
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    return status, json.loads(body)


def _make_debate(status: DebateStatus = DebateStatus.RUNNING) -> Debate:
    debate = Debate(question="Faut-il migrer vers Kubernetes ?")
    debate.status = status
    debate.owner = "admin"
    debate.participants = [
        Participant(id="a", model_id="model-a", provider="llmaas", display_name="A"),
        Participant(id="b", model_id="model-b", provider="llmaas", display_name="B"),
    ]
    return debate


def _fake_create_task(coro):
    coro.close()
    return MagicMock()


@pytest.mark.asyncio
async def test_admin_create_debate_returns_admin_stream_url():
    from app.routers import debates

    debate = _make_debate()
    orchestrator = MagicMock()
    orchestrator.create_debate.return_value = debate

    try:
        with (
            patch("app.routers.debates.get_orchestrator", return_value=orchestrator),
            patch("asyncio.create_task", side_effect=_fake_create_task),
        ):
            messages = await _call_admin_api(
                "/admin/api/debates",
                "POST",
                {
                    "question": "Faut-il migrer vers Kubernetes ?",
                    "participants": [
                        {"provider": "llmaas", "model": "model-a"},
                        {"provider": "llmaas", "model": "model-b"},
                    ],
                    "mode": "parallel",
                    "config": {"max_rounds": 3},
                },
            )
    finally:
        debates._active_debates.pop(debate.id, None)
        debates._debate_events.pop(debate.id, None)
        debates._debate_events_history.pop(debate.id, None)

    status, data = _json_response(messages)

    assert status == 200
    assert data["debate_id"] == debate.id
    assert data["stream_url"] == f"/admin/api/debates/{debate.id}/stream"
    assert debate.owner == "admin"


@pytest.mark.asyncio
async def test_admin_stream_debate_emits_ndjson_events():
    from app.routers import debates

    debate = _make_debate()
    queue = asyncio.Queue()
    await queue.put({"type": "debate_start", "debate_id": debate.id})
    await queue.put(None)
    debates._active_debates[debate.id] = debate
    debates._debate_events[debate.id] = queue

    try:
        messages = await _call_admin_api(
            f"/admin/api/debates/{debate.id}/stream",
            "GET",
        )
    finally:
        debates._active_debates.pop(debate.id, None)
        debates._debate_events.pop(debate.id, None)

    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )

    assert start["status"] == 200
    assert (b"content-type", b"application/x-ndjson") in start["headers"]
    assert json.loads(body.splitlines()[0]) == {
        "type": "debate_start",
        "debate_id": debate.id,
    }


@pytest.mark.asyncio
async def test_admin_cancel_debate_marks_debate_for_cancellation():
    from app.routers import debates

    debate = _make_debate()
    debates._active_debates[debate.id] = debate

    try:
        messages = await _call_admin_api(
            f"/admin/api/debates/{debate.id}/cancel",
            "POST",
        )
        status, data = _json_response(messages)

        assert status == 200
        assert data["status"] == "ok"
        assert debate.id in debates._cancelled_debates
    finally:
        debates._active_debates.pop(debate.id, None)
        debates._cancelled_debates.discard(debate.id)


@pytest.mark.asyncio
async def test_admin_model_health_reports_provider_statuses():
    openai_provider = MagicMock()
    openai_provider.test_connectivity = AsyncMock(return_value={
        "status": "ok",
        "models_count": 126,
    })
    anthropic_provider = MagicMock()
    anthropic_provider.test_connectivity = AsyncMock(return_value={
        "status": "error",
        "details": "HTTP 400",
    })

    router = MagicMock()
    router.loaded = True
    router.models = {
        "gpt-54": SimpleNamespace(
            id="gpt-54",
            display_name="GPT-5.4",
            provider="openai",
            category="openai",
            api_model_id="gpt-5.4",
            default=True,
            active=True,
        ),
        "claude-opus-46": SimpleNamespace(
            id="claude-opus-46",
            display_name="Claude Opus 4-6",
            provider="anthropic",
            category="anthropic",
            api_model_id="claude-opus-4-6",
            default=True,
            active=True,
        ),
    }
    router.get_status.return_value = {"providers": ["openai", "anthropic"]}
    router.get_provider.side_effect = {
        "openai": openai_provider,
        "anthropic": anthropic_provider,
    }.get

    with patch("app.services.llm.router.get_llm_router", return_value=router):
        messages = await _call_admin_api("/admin/api/model-health", "GET")

    status, data = _json_response(messages)
    providers = {p["id"]: p for p in data["providers"]}

    assert status == 200
    assert data["status"] == "degraded"
    assert data["summary"]["providers_ok"] == 1
    assert data["summary"]["providers_error"] == 1
    assert data["summary"]["models_active"] == 2
    assert providers["openai"]["status"] == "ok"
    assert providers["openai"]["upstream_models_count"] == 126
    assert providers["openai"]["models"][0]["id"] == "gpt-54"
    assert providers["anthropic"]["status"] == "error"
    assert providers["anthropic"]["details"] == "HTTP 400"

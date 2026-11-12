"""FastAPI 接口测试：SSE 流式对话、同步对话、HITL 审批恢复、会话管理与 API Key 鉴权。"""
from __future__ import annotations

import json

from starlette.testclient import TestClient

from agent.config import Config
from app.main import create_app
from tests.conftest import tool_call


def parse_sse(raw_text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in raw_text.strip().split("\n\n"):
        if not block.strip():
            continue
        ev_type = ""
        data = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                ev_type = line[7:].strip()
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        events.append((ev_type, data))
    return events


def test_healthz_and_sync_chat(make_agent):
    agent = make_agent(["你好，我是企业级小助手"])
    client = TestClient(create_app(agent))

    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert "calculator" in resp.json()["tools"]

    chat_resp = client.post("/v1/chat", json={"session_id": "web1", "message": "你好"})
    assert chat_resp.status_code == 200
    body = chat_resp.json()
    assert body["status"] == "done" and body["content"] == "你好，我是企业级小助手"


def test_sse_stream_and_hitl_approval_over_http(make_agent, config):
    agent = make_agent([
        [tool_call("write_workspace_file", {"filename": "api.md", "content": "ok"}, "w1")],
        "写入成功",
    ])
    client = TestClient(create_app(agent, config))

    stream_resp = client.post("/v1/chat/stream", json={"session_id": "s_api", "message": "写文件"})
    assert stream_resp.status_code == 200
    events = parse_sse(stream_resp.text)
    event_types = [t for t, _ in events]
    assert "run_start" in event_types and "approval_required" in event_types

    # 查看会话状态为 WAITING_APPROVAL
    sess = client.get("/v1/sessions/s_api").json()
    assert sess["status"] == "WAITING_APPROVAL"

    # 通过 /v1/chat/approve 批准恢复（非流式）
    approve_resp = client.post(
        "/v1/chat/approve",
        json={"session_id": "s_api", "approve": True, "stream": False},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "done"
    assert (config.workspace_dir / "api.md").read_text(encoding="utf-8") == "ok"

    # 删除会话
    del_resp = client.delete("/v1/sessions/s_api")
    assert del_resp.status_code == 200 and del_resp.json()["deleted"] is True


def test_api_key_authentication(make_agent, tmp_path):
    cfg = Config(api_key="test", data_dir=tmp_path, api_keys=["secret-token"])
    agent = make_agent(["通过鉴权"])
    client = TestClient(create_app(agent, cfg))

    unauth = client.post("/v1/chat", json={"session_id": "s1", "message": "hi"})
    assert unauth.status_code == 401

    ok1 = client.post(
        "/v1/chat",
        json={"session_id": "s1", "message": "hi"},
        headers={"X-API-Key": "secret-token"},
    )
    assert ok1.status_code == 200 and ok1.json()["content"] == "通过鉴权"

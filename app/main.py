"""FastAPI 异步流式网关：SSE 事件流、同步问答、高危工具人工审批（HITL）、会话管理。

启动方式::

    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from agent import __version__
from agent.config import Config, load_config
from agent.engine import Agent, AgentEvent, collect
from agent.factory import build_agent
from agent.memory import InvalidSessionId
from agent.observability import setup_logging
from app.schemas import ApproveRequest, ChatRequest, ChatResponse

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse_stream(events: AsyncIterator[AgentEvent]) -> StreamingResponse:
    async def generator() -> AsyncIterator[str]:
        async for ev in events:
            yield ev.to_sse()

    return StreamingResponse(generator(), media_type="text/event-stream", headers=SSE_HEADERS)


def create_app(agent: Agent | None = None, config: Config | None = None) -> FastAPI:
    setup_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "agent", None) is None:
            cfg = config or load_config()
            app.state.config = cfg
            app.state.agent = build_agent(cfg)
        yield
        ag: Agent | None = getattr(app.state, "agent", None)
        if ag is not None:
            await ag.memory.wait_background()

    app = FastAPI(
        title="study-agent Enterprise API",
        version=__version__,
        description="从零手写的企业级 AI Agent 服务：SSE 流式推理、分层记忆、声明式安全工具与 HITL 人工审批",
        lifespan=lifespan,
    )
    if agent is not None:
        app.state.agent = agent
        app.state.config = config or Config(api_key="injected")

    def get_agent(request: Request) -> Agent:
        return request.app.state.agent

    def verify_api_key(
        request: Request,
        x_api_key: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ) -> None:
        cfg: Config | None = getattr(request.app.state, "config", None)
        allowed = cfg.api_keys if cfg else []
        if not allowed:
            return
        token = x_api_key
        if not token and authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        if token not in allowed:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")

    @app.get("/healthz")
    async def healthz(ag: Agent = Depends(get_agent)) -> dict:
        return {"status": "ok", "version": __version__, "tools": ag.executor.registry.names()}

    @app.post("/v1/chat/stream", dependencies=[Depends(verify_api_key)])
    async def chat_stream(req: ChatRequest, ag: Agent = Depends(get_agent)) -> StreamingResponse:
        return _sse_stream(ag.chat_stream(req.session_id, req.message, user_id=req.user_id))

    @app.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
    async def chat(req: ChatRequest, ag: Agent = Depends(get_agent)) -> dict:
        return await ag.chat(req.session_id, req.message, user_id=req.user_id)

    @app.post("/v1/chat/approve", dependencies=[Depends(verify_api_key)])
    async def approve(req: ApproveRequest, ag: Agent = Depends(get_agent)):
        events = ag.resume(req.session_id, approve=req.approve, decisions=req.decisions, user_id=req.user_id)
        if req.stream:
            return _sse_stream(events)
        return await collect(events)

    @app.get("/v1/sessions/{session_id}", dependencies=[Depends(verify_api_key)])
    async def get_session(session_id: str, ag: Agent = Depends(get_agent)) -> dict:
        try:
            state = await ag.get_state(session_id)
        except InvalidSessionId as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return state.to_record()

    @app.delete("/v1/sessions/{session_id}", dependencies=[Depends(verify_api_key)])
    async def delete_session(session_id: str, ag: Agent = Depends(get_agent)) -> dict:
        try:
            deleted = await ag.reset(session_id)
        except InvalidSessionId as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"session_id": session_id, "deleted": deleted}

    return app


app = create_app()

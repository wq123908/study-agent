"""CLI 交互入口：支持流式输出、工具调用可视化、高危操作人工审批（HITL）与会话管理命令。

内置命令：
  /session <id>   切换会话
  /state          查看当前会话状态与摘要
  /trace          查看最近一次 Trace 瀑布图
  /reset          清空当前会话
  exit            退出
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from agent.config import ConfigError, load_config
from agent.engine import Agent, AgentEvent
from agent.engine.events import (
    APPROVAL_REQUIRED,
    CONTENT_DELTA,
    DONE,
    ERROR,
    STEP_START,
    THINKING_DELTA,
    TOOL_CALL_RESULT,
    TOOL_CALL_START,
)
from agent.factory import build_agent
from agent.memory import load_legacy_messages
from agent.observability import setup_logging
from agent.observability.view import render_waterfall


async def _migrate_legacy_memory(agent: Agent, session_id: str = "default") -> None:
    legacy = Path("memory.json")
    state = await agent.get_state(session_id)
    if state.messages or not legacy.exists():
        return
    try:
        msgs = load_legacy_messages(legacy)
        if msgs:
            state.messages = msgs
            await agent.memory.commit(state)
            print(f"  [迁移] 已将旧版 memory.json（{len(msgs)} 条消息）导入会话 '{session_id}'")
    except Exception as exc:  # noqa: BLE001
        print(f"  [迁移跳过] 读取旧版 memory.json 失败: {exc}")


async def _consume(agent: Agent, session_id: str, events) -> None:
    printed_content = False
    printed_thinking = False
    pending_tools: list[dict] = []

    async for ev in events:
        await _render_event(ev, printed_thinking, printed_content)
        if ev.type == THINKING_DELTA:
            printed_thinking = True
        elif ev.type == CONTENT_DELTA:
            if printed_thinking:
                print()
                printed_thinking = False
            printed_content = True
        elif ev.type == APPROVAL_REQUIRED:
            pending_tools = ev.data.get("pending_tools") or []
        elif ev.type in (TOOL_CALL_START, DONE, ERROR):
            if printed_thinking or printed_content:
                print()
                printed_thinking = printed_content = False

    if pending_tools:
        await _handle_approval(agent, session_id, pending_tools)


async def _render_event(ev: AgentEvent, printed_thinking: bool, printed_content: bool) -> None:
    data = ev.data
    if ev.type == STEP_START and data.get("step", 1) > 1:
        label = "收尾总结" if data.get("finalize") else f"第 {data['step']} 步推理"
        print(f"  ↻ [{label}]")
    elif ev.type == THINKING_DELTA:
        if not printed_thinking:
            print("  💭 ", end="", flush=True)
        print(data["delta"], end="", flush=True)
    elif ev.type == CONTENT_DELTA:
        if not printed_content:
            print("Agent：", end="", flush=True)
        print(data["delta"], end="", flush=True)
    elif ev.type == TOOL_CALL_START:
        print(f"  🔧 调用工具 {data['name']}({data['arguments']}) [{data['status']}]")
    elif ev.type == TOOL_CALL_RESULT:
        mark = "✓" if data["ok"] else f"✗ {data.get('error_type')}"
        print(f"  📎 {data['name']} {mark} ({data['duration_ms']:.1f}ms) -> {data['output_preview']}")
    elif ev.type == APPROVAL_REQUIRED:
        if data.get("content") and not printed_content:
            print(f"Agent：{data['content']}")
        print("  ⚠️  检测到高危工具调用，已挂起等待人工审批：")
        for idx, item in enumerate(data.get("pending_tools") or [], start=1):
            print(f"     {idx}. {item['name']}({item['arguments']})  [risk={item['risk_level']}]")
    elif ev.type == DONE:
        if not printed_content and data.get("content"):
            print(f"Agent：{data['content']}")
        usage = data.get("usage") or {}
        tokens_info = f"tokens={usage.get('total_tokens', '-')}" if usage else ""
        print(f"  [完成 steps={data['steps']} {data.get('duration_ms', 0):.0f}ms {tokens_info} trace={str(data.get('trace_id'))[:12]}]")
    elif ev.type == ERROR:
        print(f"  [错误 {data.get('code')}] {data.get('message')}")


async def _handle_approval(agent: Agent, session_id: str, pending_tools: list[dict]) -> None:
    loop = asyncio.get_running_loop()
    names = ", ".join(t["name"] for t in pending_tools)
    ans = (await loop.run_in_executor(None, input, f"  是否批准执行 [{names}]？(y=批准 / n=拒绝): ")).strip().lower()
    approve = ans in ("y", "yes", "是", "ok", "1")
    await _consume(agent, session_id, agent.resume(session_id, approve=approve))


async def _handle_command(cmd: str, agent: Agent, session_id: str, traces_dir: Path) -> str:
    parts = cmd.split(maxsplit=1)
    head = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if head == "/session":
        if not arg:
            print(f"  当前会话: {session_id}，已有会话: {await agent.memory.store.list_ids()}")
            return session_id
        print(f"  已切换到会话: {arg}")
        return arg
    if head == "/reset":
        await agent.reset(session_id)
        print(f"  会话 '{session_id}' 已清空")
    elif head == "/state":
        state = await agent.get_state(session_id)
        print(f"  session={state.session_id} status={state.status.value} messages={len(state.messages)}")
        if state.summary:
            print(f"  摘要: {state.summary}")
    elif head == "/trace":
        files = sorted(traces_dir.glob("*.jsonl"))
        if not files:
            print("  暂无 Trace 记录")
        else:
            last_line = [ln for ln in files[-1].read_text(encoding="utf-8").splitlines() if ln.strip()][-1]
            print(render_waterfall(json.loads(last_line)))
    else:
        print("  可用命令: /session <id> | /state | /trace | /reset | exit")
    return session_id


async def main_async() -> int:
    setup_logging("WARNING")
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"[配置错误] {exc}")
        return 1

    agent = build_agent(config)
    session_id = "default"
    await _migrate_legacy_memory(agent, session_id)

    print(f"study-agent v0.2 已启动（model={config.model}，工具={', '.join(agent.executor.registry.names())}）")
    print("输入问题开始对话；输入 /state /trace /reset /session <id> 管理会话；输入 exit 结束。")

    loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                text = await loop.run_in_executor(None, input, f"\n[{session_id}] 你：")
            except (KeyboardInterrupt, EOFError):
                print("\n再见！")
                break
            text = text.strip()
            if not text:
                continue
            if text.lower() == "exit":
                print("再见！")
                break
            if text.startswith("/"):
                session_id = await _handle_command(text, agent, session_id, config.traces_dir)
                continue
            await _consume(agent, session_id, agent.chat_stream(session_id, text))
    finally:
        await agent.memory.wait_background()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))

"""引擎端到端测试（假模型，离线）。"""
from agent.engine import collect
from agent.engine.core import DUPLICATE_CALL_NOTICE, FINALIZE_NOTICE, REJECTED_NOTICE
from agent.llm.provider import LLMError
from agent.message import ASSISTANT, TOOL, USER
from agent.state import RunStatus
from tests.conftest import ScriptedLLM, tool_call


async def events_of(agen):
    return [e async for e in agen]


async def test_plain_answer_streams_and_persists(make_agent):
    agent = make_agent(["你好，我是小助手"])
    events = await events_of(agent.chat_stream("s1", "你好"))
    types = [e.type for e in events]
    assert types[0] == "run_start" and types[-1] == "done"
    assert "".join(e.data["delta"] for e in events if e.type == "content_delta") == "你好，我是小助手"
    state = await agent.get_state("s1")
    assert [m.role for m in state.messages] == [USER, ASSISTANT]
    # system prompt 运行时注入，不落盘
    assert agent.test_llm.requests[0]["messages"][0]["role"] == "system"


async def test_tool_loop_persists_full_trajectory(make_agent):
    agent = make_agent([
        [tool_call("get_current_time", call_id="t1"), tool_call("calculator", {"expression": "1234*5678"}, "t2")],
        "现在是…，结果是 7006652",
    ])
    result = await agent.chat("s1", "现在几点？顺便算 1234*5678")
    assert result["status"] == "done" and result["steps"] == 2
    assert [r["name"] for r in result["tool_results"]] == ["get_current_time", "calculator"]
    assert result["tool_results"][1]["output_preview"] == "7006652"
    state = await agent.get_state("s1")
    assert [m.role for m in state.messages] == [USER, ASSISTANT, TOOL, TOOL, ASSISTANT]
    # 第二次请求中带上了 tool 结果
    second = agent.test_llm.requests[1]["messages"]
    assert [m["role"] for m in second[-3:]] == ["assistant", "tool", "tool"]
    # usage 汇总 + trace 导出
    assert result["usage"]["total_tokens"] == 28
    trace = agent.test_exporter.traces[-1]
    kinds = [s.kind for s in trace.spans]
    assert kinds.count("tool") == 2 and "step" in kinds and "memory" in kinds


async def test_llm_failure_keeps_history_atomic(make_agent):
    agent = make_agent(["第一轮回答"])
    await agent.chat("s1", "第一轮")
    agent.test_llm.push(LLMError("服务不可用"))
    result = await agent.chat("s1", "第二轮")
    assert result["status"] == "error" and result["error"]["code"] == "llm_error"
    state = await agent.get_state("s1")
    assert [m.content for m in state.messages] == ["第一轮", "第一轮回答"]   # 没有孤立的 user
    assert agent.test_exporter.traces[-1].status == "error"


async def test_duplicate_tool_call_guard(make_agent):
    same = {"expression": "1+1"}
    agent = make_agent([
        [tool_call("calculator", same, "a")],
        [tool_call("calculator", same, "b")],   # 重复 → 不执行，回填护栏提示
        "等于 2",
    ])
    result = await agent.chat("s1", "1+1")
    assert result["status"] == "done"
    assert [c["status"] for c in result["tool_calls"]] == ["running", "blocked"]
    assert result["tool_results"][1]["error_type"] == "duplicate_call"
    tool_msgs = [m for m in (await agent.get_state("s1")).messages if m.role == TOOL]
    assert tool_msgs[1].content == DUPLICATE_CALL_NOTICE


async def test_max_steps_forces_final_answer(make_agent, config):
    script = [[tool_call("calculator", {"expression": f"{i}+1"}, f"c{i}")] for i in range(config.max_steps)]
    agent = make_agent(script + ["根据已有结果总结"])
    result = await agent.chat("s1", "一直算")
    assert result["status"] == "done" and result["truncated"] is True
    assert result["content"] == "根据已有结果总结"
    final_request = agent.test_llm.requests[-1]
    assert final_request["tools"] is None
    assert final_request["messages"][-1]["content"] == FINALIZE_NOTICE
    # 收尾提示不落盘
    assert all(m.content != FINALIZE_NOTICE for m in (await agent.get_state("s1")).messages)


async def test_hitl_approve_flow(make_agent, config):
    agent = make_agent([
        [tool_call("write_workspace_file", {"filename": "note.md", "content": "hello"}, "w1"),
         tool_call("get_current_time", call_id="t1")],
        "文件已写入",
    ])
    first = await agent.chat("s1", "把 hello 写进 note.md")
    assert first["status"] == "waiting_approval"
    assert [p["tool_call_id"] for p in first["pending_tools"]] == ["w1"]
    assert first["pending_tools"][0]["risk_level"] == "HIGH_RISK"
    assert not (config.workspace_dir / "note.md").exists()

    state = await agent.get_state("s1")
    assert state.status is RunStatus.WAITING_APPROVAL

    # 挂起期间不能继续对话
    blocked = await agent.chat("s1", "在吗")
    assert blocked["error"]["code"] == "approval_pending"

    resumed = await collect(agent.resume("s1", approve=True))
    assert resumed["status"] == "done" and resumed["content"] == "文件已写入"
    assert (config.workspace_dir / "note.md").read_text(encoding="utf-8") == "hello"
    state = await agent.get_state("s1")
    assert state.status is RunStatus.IDLE and state.pending is None
    assert [m.role for m in state.messages] == [USER, ASSISTANT, TOOL, TOOL, ASSISTANT]


async def test_hitl_reject_flow(make_agent, config):
    agent = make_agent([
        [tool_call("write_workspace_file", {"filename": "x.md", "content": "x"}, "w1")],
        "好的，已取消",
    ])
    await agent.chat("s1", "写文件")
    resumed = await collect(agent.resume("s1", decisions={"w1": False}))
    assert resumed["status"] == "done"
    assert resumed["tool_results"][0]["error_type"] == "rejected"
    assert not (config.workspace_dir / "x.md").exists()
    tool_msg = [m for m in (await agent.get_state("s1")).messages if m.role == TOOL][0]
    assert tool_msg.content == REJECTED_NOTICE


async def test_resume_without_pending_and_missing_decision(make_agent):
    agent = make_agent([[tool_call("write_workspace_file", {"filename": "a.md", "content": "a"}, "w1")]])
    r = await collect(agent.resume("s1", approve=True))
    assert r["error"]["code"] == "no_pending_approval"
    await agent.chat("s1", "写")
    r = await collect(agent.resume("s1", decisions={}))
    assert r["error"]["code"] == "decision_required"


async def test_session_busy_and_input_validation(make_agent):
    agent = make_agent(["慢回答"])
    gen = agent.chat_stream("s1", "第一条")
    first = await gen.__anext__()                 # 第一条消息开始处理
    assert first.type == "run_start"
    busy = await collect(agent.chat_stream("s1", "第二条"))
    assert busy["error"]["code"] == "session_busy"
    rest = [e async for e in gen]
    assert rest[-1].type == "done"

    assert (await agent.chat("s1", "   "))["error"]["code"] == "invalid_input"
    assert (await agent.chat("bad/id", "hi"))["error"]["code"] == "invalid_session_id"


async def test_remember_fact_tool_and_injection(make_agent):
    agent = make_agent([
        [tool_call("remember_fact", {"fact": "用户喜欢喝美式咖啡"}, "r1")],
        "记住了",
        "你喜欢美式咖啡",
    ])
    await agent.chat("s1", "记住我喜欢喝美式咖啡", user_id="alice")
    await agent.chat("s2", "我喜欢喝什么？", user_id="alice")     # 新会话
    system = agent.test_llm.requests[-1]["messages"][0]["content"]
    assert "用户喜欢喝美式咖啡" in system


async def test_invalid_args_are_fed_back_for_self_correction(make_agent):
    agent = make_agent([
        [tool_call("calculator", {"expr": "1+1"}, "c1")],          # 参数名错误
        [tool_call("calculator", {"expression": "1+1"}, "c2")],    # 自我修正
        "等于 2",
    ])
    result = await agent.chat("s1", "1+1")
    assert result["tool_results"][0]["error_type"] == "invalid_arguments"
    assert result["tool_results"][1]["ok"] and result["content"] == "等于 2"

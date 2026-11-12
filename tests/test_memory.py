import json

import pytest

from agent.memory import (
    ContextWindowBuilder,
    InMemorySessionStore,
    JsonFileSessionStore,
    LongTermMemory,
    MemoryManager,
    Summarizer,
    load_legacy_messages,
    sanitize,
)
from agent.memory.window import MISSING_TOOL_RESULT
from agent.message import ASSISTANT, SYSTEM, TOOL, USER, Message, ToolCallItem
from agent.state import PendingApproval, RunStatus, SessionState
from tests.conftest import ScriptedLLM


def tool_turn(i: int, payload: str = "结果") -> list[Message]:
    cid = f"call_{i}"
    return [
        Message(role=USER, content=f"问题{i}"),
        Message(role=ASSISTANT, tool_calls=[ToolCallItem(id=cid, name="calculator", arguments="{}")]),
        Message(role=TOOL, tool_call_id=cid, name="calculator", content=payload),
        Message(role=ASSISTANT, content=f"回答{i}"),
    ]


# ---------------------------------------------------------------- 窗口裁剪
def test_window_keeps_whole_turns_and_never_starts_with_tool():
    messages = [m for i in range(30) for m in tool_turn(i, payload="数据" * 50)]
    sel = ContextWindowBuilder(max_tokens=600).select(messages)
    assert 0 < sel.start < len(messages)
    assert messages[sel.start].role == USER                 # 起点是轮次边界
    assert sel.messages[0].role == USER
    assert sel.tokens <= 600
    # 每个 tool_call 都有对应结果
    ids = [tc.id for m in sel.messages for tc in m.tool_calls]
    results = [m.tool_call_id for m in sel.messages if m.role == TOOL]
    assert ids == results


def test_window_always_keeps_latest_turn_even_if_over_budget():
    messages = tool_turn(0) + tool_turn(1, payload="超长" * 5000)
    sel = ContextWindowBuilder(max_tokens=500).select(messages)
    assert sel.start == 4 and len(sel.messages) == 4


def test_sanitize_drops_orphans_and_fills_missing_results():
    msgs = [
        Message(role=SYSTEM, content="旧 system"),
        Message(role=TOOL, tool_call_id="orphan", content="孤立"),
        Message(role=USER, content="hi"),
        Message(role=ASSISTANT, tool_calls=[ToolCallItem(id="a", name="x"), ToolCallItem(id="b", name="y")]),
        Message(role=TOOL, tool_call_id="a", content="ok"),
        Message(role=USER, content="next"),
    ]
    out = sanitize(msgs)
    roles = [m.role for m in out]
    assert roles == [USER, ASSISTANT, TOOL, TOOL, USER]
    assert out[3].tool_call_id == "b" and out[3].content == MISSING_TOOL_RESULT


# ---------------------------------------------------------------- 存储
async def test_json_store_roundtrip_with_tool_calls(tmp_path):
    store = JsonFileSessionStore(tmp_path)
    state = SessionState(session_id="s1", user_id="u", messages=tool_turn(0), summary="摘要",
                         status=RunStatus.WAITING_APPROVAL,
                         pending=PendingApproval(step=2, tool_call_ids=["call_0"]))
    await store.save(state)
    loaded = await store.load("s1")
    assert loaded.summary == "摘要" and loaded.status is RunStatus.WAITING_APPROVAL
    assert loaded.pending.tool_call_ids == ["call_0"]
    assert loaded.messages[1].tool_calls[0].id == "call_0"
    assert loaded.messages[2].tool_call_id == "call_0"
    assert await store.list_ids() == ["s1"]
    assert not list(tmp_path.glob("*.tmp"))


async def test_store_rejects_path_traversal(tmp_path):
    store = JsonFileSessionStore(tmp_path)
    with pytest.raises(ValueError):
        await store.load("../etc/passwd")


def test_load_legacy_memory(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(json.dumps([
        {"role": "system", "content": "旧"}, {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "嗨"},
    ], ensure_ascii=False), encoding="utf-8")
    msgs = load_legacy_messages(path)
    assert [m.role for m in msgs] == [USER, ASSISTANT]


# ---------------------------------------------------------------- 长期记忆
def test_long_term_bm25_and_isolation(tmp_path):
    lt = LongTermMemory(tmp_path / "lt.json")
    for fact in ["用户喜欢喝美式咖啡", "用户的项目使用 Python 和 FastAPI", "用户住在杭州", "用户养了一只猫"]:
        assert lt.add("alice", fact)
    assert not lt.add("alice", "用户住在杭州")             # 去重
    assert lt.search("alice", "我平时喝什么咖啡", top_k=1) == ["用户喜欢喝美式咖啡"]
    assert lt.search("alice", "fastapi 怎么部署", top_k=1) == ["用户的项目使用 Python 和 FastAPI"]
    assert lt.search("bob", "咖啡") == []
    # 持久化
    assert LongTermMemory(tmp_path / "lt.json").all("alice")[2] == "用户住在杭州"


# ---------------------------------------------------------------- 摘要
async def test_rolling_summary_triggers_when_history_slides_out():
    llm = ScriptedLLM(summary="用户问过很多计算问题")
    store = InMemorySessionStore()
    mm = MemoryManager(store, ContextWindowBuilder(max_tokens=600), Summarizer(llm),
                       summary_trigger_tokens=200, background_summary=False)
    state = SessionState(session_id="s", messages=[m for i in range(40) for m in tool_turn(i, "数据" * 40)])
    await mm.commit(state)
    assert await mm.summarize_if_needed("s")
    fresh = await store.load("s")
    assert fresh.summary == "用户问过很多计算问题"
    assert fresh.summarized_upto > 0 and fresh.messages[fresh.summarized_upto].role == USER
    # 摘要被注入 system，并且 commit 不会覆盖后台写入的摘要
    bundle = mm.build_context(fresh, fresh.messages, "SYS")
    assert "用户问过很多计算问题" in bundle.messages[0]["content"]
    await mm.commit(state)  # state 持有的是旧的 summary 字段
    assert (await store.load("s")).summary == "用户问过很多计算问题"
    assert not await mm.summarize_if_needed("s")           # 没有新的滑出内容

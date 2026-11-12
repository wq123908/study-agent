import asyncio
import json
from typing import Annotated

import pytest
from pydantic import Field

from agent.message import ToolCallItem
from agent.tools import RiskLevel, ToolContext, ToolExecutor, ToolRegistry, default_registry, safe_eval


def call(name, args=None, cid="c1"):
    return ToolCallItem(id=cid, name=name, arguments=json.dumps(args or {}))


# ---------------------------------------------------------------- 安全计算器
@pytest.mark.parametrize("expr, expected", [
    ("1234 * 5678", 7006652),
    ("12*(3+4)", 84),
    ("2**10", 1024),
    ("-3 + +5", 2),
    ("sqrt(16)", 4.0),
    ("10 // 3", 3),
    ("2^3", 8),
])
def test_safe_eval_ok(expr, expected):
    assert safe_eval(expr) == expected


@pytest.mark.parametrize("expr", [
    "__import__('os').system('echo hacked')",
    "().__class__.__bases__[0].__subclasses__()",
    "open('x.txt')",
    "a + 1",
    "9 ** 99999",
    "lambda: 1",
    "1" * 300,
])
def test_safe_eval_rejects_dangerous(expr):
    with pytest.raises((ValueError, SyntaxError)):
        safe_eval(expr)


async def test_calculator_tool_returns_string_error_instead_of_raising():
    ex = ToolExecutor(default_registry())
    r = await ex.execute_one(call("calculator", {"expression": "1/0"}))
    assert r.ok and "除数不能为 0" in r.content
    r = await ex.execute_one(call("calculator", {"expression": "__import__('os')"}))
    assert r.ok and r.content.startswith("计算错误")


# ---------------------------------------------------------------- 声明式注册
def test_schema_generated_from_signature():
    reg = ToolRegistry()

    @reg.tool(risk_level=RiskLevel.WRITE)
    def greet(name: Annotated[str, Field(description="名字")], times: int = 1, ctx: ToolContext = None) -> str:
        """打招呼"""
        return name * times

    schema = reg.get("greet").to_openai_schema()["function"]
    assert schema["name"] == "greet"
    assert schema["description"] == "打招呼"
    props = schema["parameters"]["properties"]
    assert props["name"]["description"] == "名字"
    assert props["times"]["type"] == "integer"
    assert "ctx" not in props                    # 注入参数不暴露给模型
    assert schema["parameters"]["required"] == ["name"]
    assert reg.get("greet").risk_level is RiskLevel.WRITE


def test_duplicate_and_undocumented_tools_rejected():
    reg = ToolRegistry()

    @reg.tool()
    def a() -> str:
        """doc"""
        return "a"

    with pytest.raises(ValueError):
        reg.add(a)
    with pytest.raises(ValueError):
        reg.add(lambda: "x", name="nodoc")


# ---------------------------------------------------------------- 执行器
@pytest.fixture
def registry():
    reg = ToolRegistry()

    @reg.tool(timeout=0.2)
    async def slow() -> str:
        """慢工具"""
        await asyncio.sleep(5)
        return "never"

    @reg.tool()
    async def sleepy(seconds: float) -> str:
        """睡眠"""
        await asyncio.sleep(seconds)
        return "ok"

    @reg.tool()
    def boom() -> str:
        """异常工具"""
        raise RuntimeError("内部炸了")

    @reg.tool()
    def add(a: int, b: int) -> str:
        """加法"""
        return str(a + b)

    @reg.tool()
    def whoami(ctx: ToolContext) -> str:
        """当前用户"""
        return ctx.user_id

    @reg.tool()
    def big() -> str:
        """大输出"""
        return "x" * 10_000

    return reg


async def test_argument_validation_feedback(registry):
    ex = ToolExecutor(registry)
    r = await ex.execute_one(call("add", {"a": "not-int", "b": 1}))
    assert not r.ok and r.error_type == "invalid_arguments" and "参数校验失败" in r.content
    r = await ex.execute_one(call("add", {"a": 1, "b": 2, "c": 3}))
    assert r.error_type == "invalid_arguments"            # extra=forbid
    r = await ex.execute_one(ToolCallItem(id="x", name="add", arguments="{bad json"))
    assert r.error_type == "invalid_arguments"
    r = await ex.execute_one(call("add", {"a": "3", "b": 4}))
    assert r.ok and r.content == "7"                      # 宽松类型转换


async def test_unknown_tool_timeout_exception(registry):
    ex = ToolExecutor(registry)
    assert (await ex.execute_one(call("nope"))).error_type == "unknown_tool"
    r = await ex.execute_one(call("slow"))
    assert r.error_type == "timeout" and "超时" in r.content
    r = await ex.execute_one(call("boom"))
    assert r.error_type == "exception" and "内部炸了" in r.content


async def test_context_injection_and_truncation(registry):
    ex = ToolExecutor(registry, max_output_chars=100)
    r = await ex.execute_one(call("whoami"), ToolContext(user_id="alice"))
    assert r.content == "alice"
    r = await ex.execute_one(call("big"))
    assert len(r.content) < 200 and "已截断" in r.content


async def test_batch_runs_concurrently_and_keeps_order(registry):
    ex = ToolExecutor(registry, max_concurrency=5)
    calls = [call("sleepy", {"seconds": 0.3}, cid=f"c{i}") for i in range(4)]
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    results = await ex.execute_batch(calls)
    assert loop.time() - t0 < 0.9                          # 串行需要 1.2s
    assert [r.tool_call_id for r in results] == ["c0", "c1", "c2", "c3"]


async def test_fault_injector(registry):
    ex = ToolExecutor(registry, fault_injector=lambda name: TimeoutError() if name == "add" else None)
    assert (await ex.execute_one(call("add", {"a": 1, "b": 2}))).error_type == "timeout"


async def test_workspace_file_sandbox(tmp_path):
    ex = ToolExecutor(default_registry())
    ctx = ToolContext(workspace_dir=tmp_path)
    assert ex.is_high_risk("write_workspace_file")
    r = await ex.execute_one(call("write_workspace_file", {"filename": "../evil.txt", "content": "x"}), ctx)
    assert "非法" in r.content and not (tmp_path.parent / "evil.txt").exists()
    r = await ex.execute_one(call("write_workspace_file", {"filename": "a.md", "content": "hello"}), ctx)
    assert r.ok and (tmp_path / "a.md").read_text(encoding="utf-8") == "hello"

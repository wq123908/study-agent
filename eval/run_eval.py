"""自动化回归评测流水线：覆盖工具轨迹准确率、事实忠实度、异常自愈能力三大维度。

运行方式::

    python -m eval.run_eval           # 离线确定性回放评测（CI 门禁，无需 API Key）
    python -m eval.run_eval --live    # 调用真实大模型端到端评测
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from agent.config import Config, load_config
from agent.engine import collect
from agent.factory import build_agent
from agent.llm.provider import LLMEvent
from agent.memory import InMemorySessionStore, LongTermMemory
from agent.message import ASSISTANT, TOOL, Message, ToolCallItem
from agent.observability import InMemoryTraceExporter
from agent.tools import default_registry

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "golden_cases.jsonl"


@dataclass
class CaseResult:
    case_id: str
    category: str
    trajectory_ok: bool
    illegal_tools: list[str]
    faithfulness_score: float         # 0.0 ~ 5.0
    resilience_ok: bool
    duration_ms: float
    actual_tools: list[str] = field(default_factory=list)
    answer: str = ""
    detail: str = ""


class ReplayLLM:
    """离线回放模型：支持在最终回答模板中引用最新一轮工具输出 {tool_0}, {tool_1}。"""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self._seq = 0

    async def stream_chat(self, messages: list[dict[str, Any]], tools=None) -> AsyncIterator[LLMEvent]:
        step = self.script.pop(0)
        self._seq += 1
        if isinstance(step, str):
            tool_outputs = [m["content"] for m in messages if m.get("role") == TOOL]
            text = step
            if "{tool_1}" in text:
                for idx, out in enumerate(tool_outputs):
                    text = text.replace(f"{{tool_{idx}}}", out)
            elif tool_outputs:
                text = text.replace("{tool_0}", tool_outputs[-1])
            yield LLMEvent(type="content_delta", delta=text)
            yield LLMEvent(
                type="message_complete",
                message=Message(role=ASSISTANT, content=text),
                usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            )
            return

        calls = [
            ToolCallItem(
                id=f"call_{self._seq}_{i}",
                name=item["name"],
                arguments=json.dumps(item.get("args") or {}, ensure_ascii=False),
            )
            for i, item in enumerate(step)
        ]
        yield LLMEvent(
            type="message_complete",
            message=Message(role=ASSISTANT, content=None, tool_calls=calls),
            usage={"prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26},
        )

    async def complete(self, messages: list[dict[str, Any]], *, temperature: float | None = None) -> str:
        return "摘要"


def score_faithfulness(case: dict[str, Any], result: dict[str, Any], state_messages: list[Message]) -> float:
    """确定性忠实度评分（0~5）：检查最终回答是否包含期望事实且与工具返回一致。"""
    answer = result.get("content") or ""
    if not answer.strip():
        return 0.0
    score = 5.0
    for expected in case.get("expected_substrings") or []:
        if expected not in answer:
            score -= 2.5
    tool_outputs = [m.content or "" for m in state_messages if m.role == TOOL and (m.metadata or {}).get("ok")]
    if tool_outputs and not any(
        token in answer for out in tool_outputs for token in out.split() if len(token) >= 2
    ):
        score -= 1.0
    return max(0.0, round(score, 2))


async def evaluate_case(case: dict[str, Any], *, live: bool = False, base_config: Config | None = None) -> CaseResult:
    started = time.perf_counter()
    reg = default_registry()
    valid_tool_names = set(reg.names())

    with tempfile.TemporaryDirectory() as tmp:
        cfg = base_config or Config(api_key="eval", data_dir=Path(tmp), max_steps=6)
        cfg.data_dir = Path(tmp)
        lt = LongTermMemory(None)
        for fact in case.get("seed_facts") or []:
            lt.add("eval_user", fact)

        first_timeout_target = case.get("inject_first_timeout")
        injected_once: set[str] = set()

        def fault_injector(tool_name: str):
            if first_timeout_target and tool_name == first_timeout_target and tool_name not in injected_once:
                injected_once.add(tool_name)
                return TimeoutError("simulated transient timeout")
            return None

        llm = None if live else ReplayLLM(case["script"])
        exporter = InMemoryTraceExporter()
        agent = build_agent(
            cfg,
            llm=llm,
            registry=reg,
            store=InMemorySessionStore(),
            long_term=lt,
            exporters=[exporter],
            background_summary=False,
            fault_injector=fault_injector,
        )

        result = await agent.chat(case["id"], case["input"], user_id="eval_user")
        if case.get("expect_approval"):
            if result["status"] != "waiting_approval":
                return CaseResult(
                    case_id=case["id"], category=case["category"],
                    trajectory_ok=False, illegal_tools=[], faithfulness_score=0.0,
                    resilience_ok=False, duration_ms=(time.perf_counter() - started) * 1000,
                    detail=f"期望进入 waiting_approval，实际 status={result['status']}",
                )
            resumed = await collect(agent.resume(case["id"], approve=bool(case.get("approve", True)), user_id="eval_user"))
            result["content"] = resumed["content"]
            result["status"] = resumed["status"]
            result["tool_calls"].extend(resumed["tool_calls"])
            result["tool_results"].extend(resumed["tool_results"])

        state = await agent.get_state(case["id"])

    actual_tools = [tc["name"] for tc in result["tool_calls"]]
    illegal = [t for t in actual_tools if t not in valid_tool_names]
    expected_tools = list(case.get("expected_tools") or [])
    if not expected_tools:
        trajectory_ok = len(actual_tools) == 0
    else:
        trajectory_ok = all(t in actual_tools for t in expected_tools) and not illegal

    faith = score_faithfulness(case, result, state.messages)
    resilience_ok = result["status"] == "done" and faith >= 4.0 and trajectory_ok

    return CaseResult(
        case_id=case["id"],
        category=case["category"],
        trajectory_ok=trajectory_ok,
        illegal_tools=illegal,
        faithfulness_score=faith,
        resilience_ok=resilience_ok,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
        actual_tools=actual_tools,
        answer=result.get("content") or "",
    )


async def run_suite(dataset_path: Path = DEFAULT_DATASET, *, live: bool = False) -> dict[str, Any]:
    cases = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    base_cfg = load_config() if live else None
    results = [await evaluate_case(c, live=live, base_config=base_cfg) for c in cases]

    traj_rate = sum(1 for r in results if r.trajectory_ok) / len(results)
    illegal_rate = sum(len(r.illegal_tools) for r in results) / max(1, sum(len(r.actual_tools) for r in results))
    avg_faith = sum(r.faithfulness_score for r in results) / len(results)
    resilience_cases = [r for r in results if r.category == "resilience"]
    resilience_rate = sum(1 for r in resilience_cases if r.resilience_ok) / max(1, len(resilience_cases))
    latencies = sorted(r.duration_ms for r in results)
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]

    passed = traj_rate >= 0.95 and illegal_rate == 0.0 and avg_faith >= 4.5 and resilience_rate >= 0.85
    return {
        "total_cases": len(results),
        "trajectory_recall": round(traj_rate, 4),
        "illegal_tool_rate": round(illegal_rate, 4),
        "avg_faithfulness": round(avg_faith, 2),
        "resilience_rate": round(resilience_rate, 4),
        "latency_p95_ms": round(p95, 1),
        "passed": passed,
        "cases": results,
    }


def format_report(summary: dict[str, Any]) -> str:
    lines = [
        "=" * 78,
        "study-agent 自动化回归评测报告 (LLM Evaluation Pipeline)",
        "=" * 78,
        f"{'Case ID':<26} {'类别':<12} {'轨迹':<6} {'忠实度':<8} {'自愈':<6} {'耗时(ms)':<9} 实际调用工具",
        "-" * 78,
    ]
    for r in summary["cases"]:
        lines.append(
            f"{r.case_id:<26} {r.category:<12} "
            f"{'PASS' if r.trajectory_ok else 'FAIL':<6} "
            f"{r.faithfulness_score:<8.1f} "
            f"{'PASS' if r.resilience_ok else 'FAIL':<6} "
            f"{r.duration_ms:<9.1f} {', '.join(r.actual_tools) or '(无)'}"
        )
    lines.extend([
        "-" * 78,
        f"1. 工具轨迹召回率 (SLA >= 95%)   : {summary['trajectory_recall'] * 100:.1f}%",
        f"   非法幻觉工具率 (SLA == 0%)    : {summary['illegal_tool_rate'] * 100:.1f}%",
        f"2. 平均事实忠实度 (SLA >= 4.5/5) : {summary['avg_faithfulness']:.2f} / 5.0",
        f"3. 故障自愈成功率 (SLA >= 85%)   : {summary['resilience_rate'] * 100:.1f}%",
        f"4. 端到端延迟 P95                : {summary['latency_p95_ms']:.1f} ms",
        "=" * 78,
        f"门禁结论: {'✅ 全部达标 (PASSED)' if summary['passed'] else '❌ 未达标 (FAILED)'}",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 study-agent 自动化评测集")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="黄金测试集 JSONL 路径")
    parser.add_argument("--live", action="store_true", help="调用真实大模型运行评测")
    args = parser.parse_args(argv)

    summary = asyncio.run(run_suite(args.dataset, live=args.live))
    print(format_report(summary))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""阶段 13.2–13.4 任务输入、任务结果与契约串联联验回归测试。"""
from __future__ import annotations

import json

import pytest

from agent.result import ArtifactRef, TaskError, TaskOutcome, TaskResult
from agent.run_state import RunPhase, RunRecord
from agent.task import TaskRequest


def test_task_request_text_and_structured_params_roundtrip_isolated():
    raw_params = {
        "order_id": "ORD-001",
        "items": [1, 2],
    }
    req_text = TaskRequest(
        session_id="sess_a",
        text="  生成今日巡检摘要  ",
    )
    req_params = TaskRequest(
        session_id="sess_a",
        params=raw_params,
        metadata={"source": "http"},
    )
    raw_params["order_id"] = "MUTATED"

    assert req_text.text == "生成今日巡检摘要"
    assert req_params.params["order_id"] == "ORD-001"
    assert req_text.request_id != req_params.request_id

    restored = TaskRequest.from_record(
        json.loads(
            json.dumps(
                req_params.to_record(),
                ensure_ascii=False,
            )
        )
    )
    assert restored == req_params


@pytest.mark.parametrize(
    "factory",
    [
        lambda: TaskRequest(session_id="s1", text="   "),
        lambda: TaskRequest(session_id="../etc/passwd", text="hi"),
        lambda: TaskRequest(session_id="s1", text="hi", unknown_field=1),
        lambda: TaskRequest(session_id="s1", params={"bad": object()}),
        lambda: TaskRequest(session_id="s1", params={"score": float("nan")}),
        lambda: TaskRequest.from_record(
            {
                "session_id": "s1",
                "text": "hi",
                "created_at": 1.0,
            }
        ),
    ],
)
def test_task_request_rejects_invalid_inputs(factory):
    with pytest.raises(ValueError):
        factory()


def test_task_result_outcomes_and_artifacts_roundtrip():
    ok = TaskResult(
        run_id="run_001",
        outcome=TaskOutcome.SUCCEEDED,
        text="巡检完成",
        data={"count": 2},
        artifacts=[
            ArtifactRef(
                kind="file",
                locator="workspace://report.md",
                media_type="text/markdown",
            ),
            ArtifactRef(
                kind="json",
                locator="workspace://metrics.json",
                media_type="application/json",
                metadata={"rows": 2},
            ),
        ],
    )
    ok_back = TaskResult.from_record(
        json.loads(
            json.dumps(
                ok.to_record(),
                ensure_ascii=False,
            )
        )
    )
    assert ok_back == ok
    assert [a.kind for a in ok_back.artifacts] == ["file", "json"]

    # 程序执行到 COMPLETED，但业务结果判定为 FAILED
    failed = TaskResult(
        run_id="run_002",
        run_phase=RunPhase.COMPLETED,
        outcome=TaskOutcome.FAILED,
        error=TaskError(
            code="condition_unmet",
            message="未满足必选回执要求",
            source="policy",
        ),
    )
    failed_back = TaskResult.from_record(
        json.loads(
            json.dumps(
                failed.to_record(),
                ensure_ascii=False,
            )
        )
    )
    assert failed_back == failed
    assert failed_back.run_phase is RunPhase.COMPLETED
    assert failed_back.outcome is TaskOutcome.FAILED
    assert failed_back.error is not None and failed_back.error.source == "policy"

    verify = TaskResult(
        run_id="run_003",
        outcome=TaskOutcome.NEEDS_VERIFICATION,
        text="写操作超时，需对账确认",
    )
    verify_back = TaskResult.from_record(
        json.loads(
            json.dumps(
                verify.to_record(),
                ensure_ascii=False,
            )
        )
    )
    assert verify_back == verify


@pytest.mark.parametrize(
    "factory",
    [
        lambda: TaskResult(
            run_id="run_1",
            outcome=TaskOutcome.SUCCEEDED,
            error=TaskError(code="e", message="m"),
        ),
        lambda: TaskResult(
            run_id="run_1",
            run_phase=RunPhase.FAILED,
            outcome=TaskOutcome.SUCCEEDED,
        ),
        lambda: TaskResult(
            run_id="run_1",
            outcome=TaskOutcome.FAILED,
        ),
        lambda: TaskResult(
            run_id="run_1",
            outcome=TaskOutcome.NEEDS_VERIFICATION,
        ),
        lambda: TaskResult(
            run_id="run_1",
            outcome=TaskOutcome.SUCCEEDED,
            artifacts=[
                ArtifactRef(artifact_id="art_dup", kind="file", locator="a"),
                ArtifactRef(artifact_id="art_dup", kind="json", locator="b"),
            ],
        ),
    ],
)
def test_task_result_rejects_contradictions(factory):
    with pytest.raises(ValueError):
        factory()


def test_two_tasks_in_same_session_end_to_end_contract_roundtrip():
    """联验：同会话两条独立任务 → 各自运行记录 → 各自结果 → 整包 JSON 往返校验。"""
    session_id = "sess_shared"

    req_a = TaskRequest(
        session_id=session_id,
        text="导出日报",
    )
    run_a = RunRecord(
        session_id=req_a.session_id,
        phase=RunPhase.COMPLETED,
    )
    res_a = TaskResult(
        run_id=run_a.run_id,
        run_phase=run_a.phase,
        outcome=TaskOutcome.SUCCEEDED,
        text="日报导出成功",
        artifacts=[
            ArtifactRef(
                kind="file",
                locator="workspace://daily.md",
                media_type="text/markdown",
            )
        ],
    )

    req_b = TaskRequest(
        session_id=session_id,
        params={"action": "sync", "target": "erp"},
    )
    run_b = RunRecord(
        session_id=req_b.session_id,
        phase=RunPhase.COMPLETED,
    )
    res_b = TaskResult(
        run_id=run_b.run_id,
        run_phase=run_b.phase,
        outcome=TaskOutcome.FAILED,
        error=TaskError(
            code="remote_rejected",
            message="下游拒绝同步",
            source="tool",
        ),
    )

    bundle = {
        "a": {
            "request": req_a.to_record(),
            "run": run_a.to_record(),
            "result": res_a.to_record(),
        },
        "b": {
            "request": req_b.to_record(),
            "run": run_b.to_record(),
            "result": res_b.to_record(),
        },
    }
    loaded = json.loads(
        json.dumps(
            bundle,
            ensure_ascii=False,
        )
    )

    req_a2 = TaskRequest.from_record(loaded["a"]["request"])
    run_a2 = RunRecord.from_record(loaded["a"]["run"])
    res_a2 = TaskResult.from_record(loaded["a"]["result"])

    req_b2 = TaskRequest.from_record(loaded["b"]["request"])
    run_b2 = RunRecord.from_record(loaded["b"]["run"])
    res_b2 = TaskResult.from_record(loaded["b"]["result"])

    assert req_a2.session_id == req_b2.session_id == session_id
    assert run_a2.session_id == run_b2.session_id == session_id
    assert run_a2.run_id != run_b2.run_id
    assert res_a2.run_id == run_a2.run_id
    assert res_b2.run_id == run_b2.run_id
    assert res_a2.outcome is TaskOutcome.SUCCEEDED
    assert res_b2.outcome is TaskOutcome.FAILED
    assert res_b2.run_phase is RunPhase.COMPLETED
    assert req_a2 == req_a and run_a2 == run_a and res_a2 == res_a
    assert req_b2 == req_b and run_b2 == run_b and res_b2 == res_b
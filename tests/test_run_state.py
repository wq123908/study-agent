"""阶段 13.1 独立运行记录契约回归测试。"""
from __future__ import annotations

import json

import pytest

from agent.run_state import RunPhase, RunRecord
from agent.state import RunStatus, SessionState


def test_same_session_runs_are_independent():
    r1 = RunRecord(session_id="sess_1")
    r2 = RunRecord(session_id="sess_1")

    assert r1.run_id != r2.run_id
    assert r1.run_id.startswith("run_")
    assert r1.phase is RunPhase.CREATED
    assert r2.phase is RunPhase.CREATED

    r1.phase = RunPhase.WAITING
    assert r2.phase is RunPhase.CREATED


def test_run_record_json_roundtrip_preserves_identity_and_timestamps():
    original = RunRecord(
        session_id="sess_1",
        run_id="run_fixed_001",
        phase=RunPhase.RUNNING,
        created_at=1700000000.5,
        updated_at=1700000010.5,
    )
    encoded = json.dumps(
        original.to_record(),
        ensure_ascii=False,
    )
    restored = RunRecord.from_record(json.loads(encoded))

    assert restored == original
    assert restored.run_id == "run_fixed_001"
    assert restored.created_at == 1700000000.5
    assert restored.updated_at == 1700000010.5
    assert restored.phase is RunPhase.RUNNING


def test_run_record_coexists_with_v1_session_state():
    session = SessionState(session_id="sess_1")
    run = RunRecord(session_id=session.session_id)

    assert session.status is RunStatus.IDLE
    assert run.phase is RunPhase.CREATED


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-dict",
        {"session_id": "s1", "phase": "CREATED", "created_at": 1.0},
        {"run_id": "", "session_id": "s1", "phase": "CREATED", "created_at": 1.0},
        {"run_id": "run_1", "phase": "CREATED", "created_at": 1.0},
        {"run_id": "run_1", "session_id": "s1", "phase": "FLYING", "created_at": 1.0},
        {"run_id": "run_1", "session_id": "s1", "phase": "CREATED"},
        {"run_id": "run_1", "session_id": "s1", "phase": "CREATED", "created_at": True},
        {
            "run_id": "run_1",
            "session_id": "s1",
            "phase": "CREATED",
            "created_at": 1.0,
            "version": 0,
        },
    ],
)
def test_run_record_rejects_corrupted_or_invalid_records(raw):
    with pytest.raises(ValueError):
        RunRecord.from_record(raw)


def test_run_record_rejects_blank_session_id():
    with pytest.raises(ValueError):
        RunRecord(session_id="   ")
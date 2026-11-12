"""在终端以瀑布图形式查看 Trace。

    python -m agent.observability.view            # 最近一条
    python -m agent.observability.view <trace_id> # 指定（支持前缀）
    python -m agent.observability.view --list 10  # 最近 10 条概览
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent.config import load_config


def _load_traces(directory: Path) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                traces.append(json.loads(line))
    return traces


def render_waterfall(trace: dict[str, Any], width: int = 40) -> str:
    total = trace.get("duration_ms") or 1.0
    start0 = trace["start"]
    lines = [
        f"Trace {trace['trace_id']}  session={trace['session_id']}  status={trace['status']}",
        f"输入: {str(trace.get('input'))[:80]}",
        f"总耗时: {total:.0f} ms   Token: {trace.get('usage') or {}}",
        "-" * (width + 60),
    ]
    spans = trace.get("spans", [])
    children: dict[str | None, list[dict[str, Any]]] = {}
    for sp in spans:
        children.setdefault(sp.get("parent_id"), []).append(sp)
    for group in children.values():
        group.sort(key=lambda s: s["start"])

    def walk(parent_id: str | None, depth: int) -> None:
        for sp in children.get(parent_id, []):
            offset = int((sp["start"] - start0) * 1000 / total * width)
            length = max(1, int((sp.get("duration_ms") or 0) / total * width))
            bar = " " * min(offset, width) + "█" * min(length, width - min(offset, width) or 1)
            label = f"{'  ' * depth}{sp['kind']}:{sp['name']}"
            flag = "" if sp.get("status") == "ok" else f"  ✗ {sp.get('error')}"
            extra = ""
            attrs = sp.get("attributes") or {}
            if "ttft_ms" in attrs:
                extra = f"  ttft={attrs['ttft_ms']}ms"
            lines.append(f"{label:<34}|{bar:<{width}}| {sp.get('duration_ms') or 0:>8.1f} ms{extra}{flag}")
            walk(sp["span_id"], depth + 1)

    walk(None, 0)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="查看 Agent Trace 瀑布图")
    parser.add_argument("trace_id", nargs="?", help="Trace ID 或前缀，缺省为最近一条")
    parser.add_argument("--list", type=int, metavar="N", help="列出最近 N 条 Trace 概览")
    parser.add_argument("--dir", type=Path, help="Trace 目录，默认 data/traces")
    args = parser.parse_args(argv)

    directory = args.dir or load_config(require_api_key=False).traces_dir
    traces = _load_traces(directory)
    if not traces:
        print(f"{directory} 下没有 Trace 记录")
        return 1

    if args.list:
        for t in traces[-args.list:]:
            print(f"{t['trace_id'][:12]}  {t['status']:<5} {t.get('duration_ms') or 0:>8.0f}ms  "
                  f"{t['session_id']:<12} {str(t.get('input'))[:40]}")
        return 0

    if args.trace_id:
        matched = [t for t in traces if t["trace_id"].startswith(args.trace_id)]
        if not matched:
            print(f"未找到 Trace: {args.trace_id}")
            return 1
        trace = matched[-1]
    else:
        trace = traces[-1]
    print(render_waterfall(trace))
    return 0


if __name__ == "__main__":
    sys.exit(main())

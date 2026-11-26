"""L3 长期记忆：按用户隔离的事实库 + BM25 词法检索（中文按单字/二元组切分）。

本实现零依赖、落盘为 JSON，适合单机；接口（add/search/all/delete）与向量库实现保持一致，
生产环境可替换为 pgvector / Chroma 的混合检索实现。
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

_ASCII_WORD = re.compile(r"[a-z0-9_]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")

def tokenize(text: str) -> list[str]:
    """零依赖中英文分词：英文/数字按词切分，连续汉字同时切出单字与二元组（bigram）。"""
    text = text.lower()
    tokens = _ASCII_WORD.findall(text)
    for run in _CJK_RUN.findall(text):
        tokens.extend(run)                                         # 单字，保底召回
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1)) # 二元组，锁准词义
    return tokens

class LongTermMemory:
    def __init__(
        self,
        path: str | Path | None = None,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.path = Path(path) if path else None
        self.k1 = k1                                # 词频饱和度参数：重复词收益递减
        self.b = b                                  # 文档长度归一化：防长文本靠堆字霸榜
        self._lock = threading.Lock()               # 线程锁（同步工具可能跑在 to_thread 线程池）
        self._data: dict[str, list[dict[str, Any]]] = self._load()

    # ---------- 持久化 ----------
    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if self.path and self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {}
    
    def _flush(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                self._data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.path)
    
    # ---------- 读写 ----------
    def add(
        self,
        user_id: str,
        text: str,
    ) -> bool:
        text = text.strip()
        if not text:
            return False
        with self._lock:
            facts = self._data.setdefault(
                user_id,
                [],
            )
            # 精确去重：同样的一条事实不重复塞进库
            if any(f["text"] == text for f in facts):
                return False
            facts.append(
                {
                    "id": uuid.uuid4().hex[:8],
                    "text": text,
                    "created_at": time.time(),
                }
            )
            self._flush()
            return True

    def all(self, user_id: str) -> list[str]:
        with self._lock:
            return [f["text"] for f in self._data.get(user_id, [])]

    def delete(
        self,
        user_id: str,
        fact_id: str,
    ) -> bool:
        with self._lock:
            facts = self._data.get(user_id, [])
            remaining = [f for f in facts if f["id"] != fact_id]
            if len(remaining) == len(facts):
                return False
            self._data[user_id] = remaining
            self._flush()
            return True

    def search(
        self,
        user_id: str,
        query: str,
        top_k: int = 3,
    ) -> list[str]:
        """事实总数不超过 top_k 时直接全部返回；否则按 BM25 取得分 > 0 的 top_k。"""
        facts = self.all(user_id)
        if len(facts) <= top_k:
            return facts
        q_tokens = set(tokenize(query))
        if not q_tokens:
            return []

        docs = [tokenize(f) for f in facts]
        avg_len = sum(len(d) for d in docs) / len(docs) or 1.0
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)

        scored: list[tuple[float, int]] = []
        for idx, doc in enumerate(docs):
            tf = Counter(doc)
            score = 0.0
            for term in q_tokens:
                if term not in tf:
                    continue
                # IDF：越稀缺的词权重越高；加 1 保证非负
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                freq = tf[term]
                denom = freq + self.k1 * (1 - self.b + self.b * len(doc) / avg_len)
                score += idf * freq * (self.k1 + 1) / denom
            if score > 0:
                scored.append((score, idx))
        # 按分数降序，同分时按原写入顺序稳定排序
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [facts[idx] for _, idx in scored[:top_k]]   
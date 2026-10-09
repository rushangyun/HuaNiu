"""搜索策略：把"试什么"具体化成一组候选，并按历史剪枝。

两个职责：
  1. build_pool()        —— 生成候选池（基线 + 单点扰动），顺序是"先稳后激进"
  2. prune_with_history —— 根据历史里的 OOM 记录，砍掉显然会爆显存的候选

LLM 只是"顾问"，不参与主流程；主流程必须不依赖网络也能跑通。
"""

from __future__ import annotations

from .experiment import Experiment, STATUS_OOM
from .space import SEARCH_SPACE, DEFAULTS, param_names


def baseline() -> dict:
    """默认那组超参，作为候选池的起点。"""
    return {k: DEFAULTS[k] for k in param_names()}


def build_pool() -> list[dict]:
    """候选池：先放基线，再对每个参数在中点附近扰动，去重后返回。"""
    cands: list[dict] = [baseline()]
    for p in SEARCH_SPACE:
        for v in p.values:
            cand = baseline()
            cand[p.name] = v
            cands.append(cand)

    seen: set[tuple] = set()
    uniq: list[dict] = []
    for c in cands:
        key = tuple(sorted((k, c[k]) for k in param_names()))
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


def min_oom_batch(history: list[Experiment]) -> int | None:
    """历史里"最小的那次 OOM batch"。任何 >= 它的 batch 都别再试。"""
    batches = [
        int(e.params["batch"]) for e in history
        if e.status == STATUS_OOM and "batch" in e.params
    ]
    return min(batches) if batches else None


def prune_with_history(pool: list[dict], history: list[Experiment]) -> list[dict]:
    """砍掉会 OOM 的候选：batch >= 历史最小 OOM batch 的一律剔除。"""
    floor = min_oom_batch(history)
    if floor is None:
        return pool
    return [c for c in pool if int(c["batch"]) < floor]

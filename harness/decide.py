"""决策器：根据历史决定"下一组试什么"。

默认走确定性策略（候选池 + OOM 剪枝），保证断网也能跑。
若 Ollama 在线且显式开启 --llm，会让本地大模型当"顾问"推荐下一组超参，
它的建议可能编出空间外的取值，所以一律过一遍 clamp_to_space 拉回合法候选。

无论哪条路径，最终都会用 clamp_to_space 兜底——这是闭环不会因为
"模型说了一个不存在的学习率"而崩的关键。
"""

from __future__ import annotations

import json
import urllib.request

from .experiment import Experiment
from .space import SEARCH_SPACE, DEFAULTS, Budget, clamp_to_space, param_names, EXCLUSIONS
from .strategy import baseline, build_pool, prune_with_history

OLLAMA_URL = "http://127.0.0.1:11434/v1/chat/completions"
LLM_MODEL = "qwen2.5:7b-instruct"


def decide_next(history: list[Experiment], budget: Budget,
                use_llm: bool = False) -> dict | None:
    """返回下一组要试的超参；候选池试完则返回 None。"""
    pool = prune_with_history(build_pool(), history)
    tried = {tuple(sorted(e.params.items())) for e in history}

    if use_llm:
        sugg = _ask_llm(history, budget)
        if sugg:
            # 用基线补齐缺失字段，再把取值夹回合法候选
            merged = {**baseline(), **clamp_to_space(sugg)}
            if tuple(sorted(merged.items())) not in tried:
                return merged
            # 否则退回池子接着挑

    for cand in pool:
        if tuple(sorted(cand.items())) not in tried:
            return cand
    return None  # 池子试完了


def _ask_llm(history: list[Experiment], budget: Budget) -> dict | None:
    """让本地大模型基于历史推荐下一组超参。失败就返回 None（交给策略兜底）。"""
    space_desc = "\n".join(
        f"  - {p.name}: 候选 {p.values}（{p.desc}）" for p in SEARCH_SPACE
    )
    excl_desc = "\n".join(
        f"  - {x.dimension}：{x.verdict}。证据：{x.evidence} "
        f"应改试：{x.try_instead}" for x in EXCLUSIONS
    ) or "（无）"
    hist_lines = [e.summary_line() for e in history] or ["（暂无历史）"]
    prompt = (
        "你在一个 YOLO 超参搜索闭环里当决策顾问。\n"
        f"可搜参数与合法候选：\n{space_desc}\n\n"
        "已用实验数据排除、不要再浪费预算的维度：\n"
        f"{excl_desc}\n\n"
        "已做实验：\n" + "\n".join(hist_lines) + "\n\n"
        "请推荐下一组要试的超参，只从上面候选里选，避免已 OOM 的 batch/imgsz，"
        "也**不要**建议通过'训更久/调大 epochs'来提精度——这已被实验证明无效。"
        "只输出一个 JSON 对象，例如 "
        '{"mosaic":1.0,"mixup":0.0,"copy_paste":0.0,"lr0":0.01,"batch":16,'
        '"imgsz":640,"momentum":0.937,"weight_decay":0.0005,'
        '"warmup_epochs":3.0}，不要解释。'
    )
    try:
        payload = json.dumps({
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }).encode("utf-8")
        req = urllib.request.Request(
            OLLAMA_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        content = out["choices"][0]["message"]["content"]
        return _extract_json(content)
    except Exception:  # noqa: BLE001
        return None


def _extract_json(text: str) -> dict | None:
    """从模型回复里尽量抠出第一个 JSON 对象。"""
    try:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return None
        return json.loads(text[start:end + 1])
    except Exception:  # noqa: BLE001
        return None

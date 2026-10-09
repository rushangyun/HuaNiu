# Harness · 自主实验闭环

题目第四部分：**让程序自己反复跑训练、比数字、决定下一组超参**。

不依赖 Dify / 框架，纯手写一个"试 → 记 → 学 → 再试"的闭环。
核心思想：**失败（含 OOM）也是一条实验记录**，闭环靠它学会避开跑不起来的参数。

## 文件职责

| 文件 | 职责 |
|---|---|
| `space.py` | 搜索空间定义：`SEARCH_SPACE` / `DEFAULTS` / `Budget` / `clamp_to_space` |
| `experiment.py` | 实验记录：`Experiment`（`ok`/`oom`/`failed` 三态）、`experiments.jsonl` 读写 |
| `runner.py` | 执行器：子进程调用 `training/train.py`，读 `result.json` 翻成记录 |
| `strategy.py` | 策略：生成候选池 + 按历史 OOM 剪枝 |
| `decide.py` | 决策器：决定下一组试什么（策略兜底，可选让本地大模型当顾问） |
| `run.py` | 主入口：组装上面的模块成闭环 |

## 运行

```bash
# 默认：8 组、每组 8 epoch，纯策略（断网也能跑）
python harness/run.py

# 少试几组、每组少跑点，先验证闭环通不通
python harness/run.py --max-trials 4 --epochs 5

# 让本地 qwen2.5:7b 当决策顾问（需 ollama serve 在线）
python harness/run.py --llm

# 清空历史重来
python harness/run.py --reset
```

## 闭环怎么"学"

1. `runner` 用子进程跑一次 `training/train.py --no-export --result-out <path>`，
   训练脚本把结论写成机器可读的 `result.json`，不抛异常。
2. `runner` 把 `result.json` 翻成 `Experiment`：成功=ok，OOM=oom，其他=failed。
3. `append` 追加进 `runs/harness/experiments.jsonl`（一行一条，便于中断续跑）。
4. 下一轮 `decide` 读历史：凡是历史里 OOM 过的 `batch` 及以上，直接从候选池剔除，
   于是闭环**自动避开显存不够的配置**——这就是"自主"的含义。

## 产出

- `runs/harness/experiments.jsonl` —— 全部实验记录（含失败）
- `runs/harness/report.md` —— 人类可读的汇总与最佳配置
- `models/yolo/best.pt` —— 闭环里 mAP 最高的那次自动导出

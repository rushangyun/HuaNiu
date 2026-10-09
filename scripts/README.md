# scripts/ — 脚本

## gen_event_types.py

把 Python 的事件契约转成 TypeScript 类型。

```bash
python scripts/gen_event_types.py
```

- 读：`server/app/core/events.py`
- 写：`web/src/types/events.ts`

原理：解析 Python AST，抽出事件类型常量和 dataclass 字段，输出 TS 接口。

**改完 `server/app/core/events.py` 必须重跑一次**，否则前后端会悄悄漂移——
这是解耦架构最常见的翻车方式：两边都觉得自己没错，运行时才发现对不上。

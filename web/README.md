# web/ — 前端

React + Vite + TypeScript，浅色简洁风格。

**这一层只做两件事：组织 UI、订阅事件。** 没有计算，没有模型调用，
不知道后端是怎么把答案算出来的。

## 启动

```bash
npm install
npm run dev        # http://127.0.0.1:5173
npm run typecheck  # 只做类型检查
```

`/api` 由 Vite 代理到后端 8000 端口（见 `vite.config.ts`），
所以组件里永远写相对路径，部署时换代理目标即可。

## 分层

```
src/
  types/events.ts   ★ 自动生成，不要手改
  api/stream.ts     SSE 订阅与解析（无 React、无 UI 状态）
  hooks/useChat.ts  事件流 → 视图模型的映射
  components/       纯展示
    StatusBar       顶栏状态点（自己订阅 /api/health）
    MessageBubble   消息 + 它调用过的工具
    Composer        输入区
  App.tsx           只做组装
```

**为什么要把「事件 → 状态」单独放在 hooks 里：**
后端加一种新事件，只需要在这里多写一个 `case`，组件可能一行都不用改。

## 事件契约

`src/types/events.ts` 由 `scripts/gen_event_types.py` 从
`server/app/core/events.py` 自动生成。改了后端事件定义之后：

```bash
python scripts/gen_event_types.py
```

不要手改这个文件，手抄的类型一定会和实现漂移。

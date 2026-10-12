# web/src — 前端源码

前端只做两件事：**组织 UI + 订阅事件**。它不知道后端怎么实现，只认 `types/events.ts` 这份契约。

| 目录 / 文件 | 干什么 |
|---|---|
| `main.tsx` | ★ 组合根：挂载 React、注入 client |
| `App.tsx` | 纯 UI 组织（对话 / 视觉 / 有声书三个视图切换） |
| `types/events.ts` | ★ 与后端 `core/events.py` **一一对应**，由 `scripts/gen_event_types.py` 自动生成，**不手抄** |
| [`api/`](api/README.md) | 唯一的后端耦合点（HTTP + SSE 订阅） |
| [`hooks/`](hooks/README.md) | 订阅逻辑，组件里不写网络代码 |
| [`components/`](components/README.md) | 纯展示组件 |
| `styles.css` | 浅色简洁主题 |

## 分工红线

**组件里不出现 `fetch` / `EventSource`**，网络代码全在 `api/` 和 `hooks/`。

违反这条，组件就和后端耦合在一起，既没法单独复用，也没法单独改。

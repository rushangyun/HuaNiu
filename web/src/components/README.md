# web/src/components — 纯展示组件

| 文件 | 干什么 |
|---|---|
| `Composer.tsx` | 输入框 |
| `MessageBubble.tsx` | 对话气泡（含工具调用过程的可视化） |
| `StatusBar.tsx` | 连接状态 |
| `VisionPanel.tsx` | 视觉检测画面（`<img>` 直接吃 MJPEG 流） |
| `AudiobookView.tsx` | 有声书：创作台 / 解析进度 / 角色音色配置 / 合成 / 试听 / 下载 |

## 规则

**这里不出现 `fetch` / `EventSource`** —— 数据一律由 `hooks/` 传入，
用户操作（发消息、选音色、点合成）也通过回调交给 hook。

组件只负责"把状态画出来"，所以能单独复用，也不依赖后端实现。

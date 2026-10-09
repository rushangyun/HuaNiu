/**
 * 应用外壳：只做组装——把状态 hook、输入区、消息列表、状态栏拼在一起。
 * 这里没有网络请求、没有事件解析，那些都在 api/ 和 hooks/ 里。
 */

import { useEffect, useRef } from "react";
import { Composer } from "./components/Composer";
import { MessageBubble } from "./components/MessageBubble";
import { StatusBar } from "./components/StatusBar";
import { useChat } from "./hooks/useChat";

export default function App() {
  const { messages, busy, send, stop, clear } = useChat();
  const bottomRef = useRef<HTMLDivElement>(null);

  // 有新内容就滚到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="app">
      <header className="topbar">
        <h1>
          华小牛 HuaNiu
          <span className="sub">本地优先的视觉智能体</span>
        </h1>
        <StatusBar />
      </header>

      <div className="messages">
        {messages.length === 0 ? (
          <div className="empty">
            <strong>想问点什么？</strong>
            模型跑在你自己机器上，断网也能用。
            <br />
            试试「现在几点」「算一下 12345 × 6789」「看看工程里有什么文件」
          </div>
        ) : (
          messages.map((m) => <MessageBubble key={m.id} msg={m} />)
        )}
        <div ref={bottomRef} />
      </div>

      <Composer busy={busy} onSend={send} onStop={stop} onClear={clear} />
    </div>
  );
}

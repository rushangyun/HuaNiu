/** 输入区：只负责收集用户输入，不含任何业务逻辑。 */

import { useState, type KeyboardEvent } from "react";

interface Props {
  busy: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  onClear: () => void;
}

export function Composer({ busy, onSend, onStop, onClear }: Props) {
  const [text, setText] = useState("");

  const submit = () => {
    if (!text.trim() || busy) return;
    onSend(text);
    setText("");
  };

  // Enter 发送，Shift+Enter 换行——聊天界面的通用约定
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="composer">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="问点什么……（Enter 发送，Shift+Enter 换行）"
        disabled={false}
      />
      {busy ? (
        <button className="ghost" onClick={onStop}>
          停止
        </button>
      ) : (
        <button onClick={submit} disabled={!text.trim()}>
          发送
        </button>
      )}
      <button className="ghost" onClick={onClear} title="清空对话">
        清空
      </button>
    </div>
  );
}

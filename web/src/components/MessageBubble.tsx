/** 单条消息的展示：正文 + 它调用过的工具 + 出错信息。 */

import type { ToolCallView } from "../hooks/useChat";

export interface MessageLike {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: ToolCallView[];
  error?: string;
  pending: boolean;
}

export function MessageBubble({ msg }: { msg: MessageLike }) {
  return (
    <div className={`msg ${msg.role}`}>
      {msg.tools.length > 0 && (
        <div className="tools">
          {msg.tools.map((t) => (
            <ToolCallCard key={t.key} tool={t} />
          ))}
        </div>
      )}

      {msg.error ? (
        <div className="bubble error">{msg.error}</div>
      ) : (
        (msg.content || msg.pending) && (
          <div className="bubble">
            {msg.content}
            {msg.pending && <span className="caret" />}
          </div>
        )
      )}
    </div>
  );
}

function ToolCallCard({ tool }: { tool: ToolCallView }) {
  return (
    <div className="tool">
      <div className="tool-head">
        {tool.running ? <span className="spinner" /> : <span className="dot ok" />}
        <span className="tool-name">{tool.name}</span>
        {tool.running && <span>执行中…</span>}
      </div>

      {tool.args && Object.keys(tool.args).length > 0 && (
        <div className="tool-args">{formatArgs(tool.args)}</div>
      )}
      {tool.result && <div className="tool-result">{tool.result}</div>}
    </div>
  );
}

/** 参数显示成 `key=value` 一行，比裸 JSON 好读 */
function formatArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("  ·  ");
}

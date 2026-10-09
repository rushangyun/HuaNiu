/**
 * 把后端事件流映射成界面状态。
 *
 * 这一层是"前端只负责组织和订阅"的关键：
 * 组件不直接碰事件流，而是消费这里产出的视图模型（MessageView）。
 * 后端加一种新事件，只需要在这里多写一个 case，组件可能完全不用改。
 */

import { useCallback, useRef, useState } from "react";
import { streamChat } from "../api/stream";
import {
  DONE,
  ERROR,
  TOKEN,
  TOOL_END,
  TOOL_START,
  type AgentEvent,
} from "../types/events";

export interface ToolCallView {
  key: string;
  name: string;
  args?: Record<string, unknown>;
  result?: string;
  running: boolean;
}

export interface MessageView {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: ToolCallView[];
  error?: string;
  pending: boolean;
}

let seq = 0;
const nextId = () => `m${++seq}`;

export function useChat() {
  const [messages, setMessages] = useState<MessageView[]>([]);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  /** 把当前对话整理成后端要的 history 格式 */
  const buildHistory = (list: MessageView[]) =>
    list
      .filter((m) => !m.pending && !m.error)
      .map((m) => ({ role: m.role, content: m.content }));

  const send = useCallback(async (text: string) => {
    const content = text.trim();
    if (!content || busy) return;

    const userMsg: MessageView = {
      id: nextId(),
      role: "user",
      content,
      tools: [],
      pending: false,
    };
    const assistantId = nextId();

    let history: Array<{ role: "user" | "assistant"; content: string }> = [];

    setMessages((prev) => {
      history = buildHistory(prev);
      return [
        ...prev,
        userMsg,
        { id: assistantId, role: "assistant", content: "", tools: [], pending: true },
      ];
    });
    setBusy(true);

    const controller = new AbortController();
    abortRef.current = controller;

    /** 统一改某条消息 */
    const patch = (id: string, fn: (m: MessageView) => MessageView) =>
      setMessages((prev) => prev.map((m) => (m.id === id ? fn(m) : m)));

    try {
      for await (const ev of streamChat(
        { message: content, history },
        controller.signal
      )) {
        applyEvent(ev, assistantId, patch);
      }
      // 流正常结束但没收到 done，也把 pending 摘掉，避免一直转圈
      patch(assistantId, (m) => ({ ...m, pending: false }));
    } catch (err) {
      if ((err as Error)?.name === "AbortError") {
        patch(assistantId, (m) => ({ ...m, pending: false }));
      } else {
        patch(assistantId, (m) => ({
          ...m,
          pending: false,
          error: err instanceof Error ? err.message : String(err),
        }));
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }, [busy]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const clear = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
  }, []);

  return { messages, busy, send, stop, clear };
}

/** 单个事件如何改变一条消息。抽出来是为了好测、好读。 */
function applyEvent(
  ev: AgentEvent,
  id: string,
  patch: (id: string, fn: (m: MessageView) => MessageView) => void
) {
  switch (ev.type) {
    case TOKEN:
      patch(id, (m) => ({ ...m, content: m.content + (ev.text ?? "") }));
      break;

    case TOOL_START:
      patch(id, (m) => ({
        ...m,
        tools: [
          ...m.tools,
          {
            key: `${id}-t${m.tools.length}`,
            name: ev.name ?? "未知工具",
            args: ev.arguments,
            running: true,
          },
        ],
      }));
      break;

    case TOOL_END:
      patch(id, (m) => {
        // 匹配最后一个还在跑的同名工具——一次对话里同名工具可能调多次
        const idx = [...m.tools].reverse().findIndex((t) => t.running && t.name === ev.name);
        if (idx === -1) return m;
        const target = m.tools.length - 1 - idx;
        const tools = [...m.tools];
        tools[target] = { ...tools[target], result: ev.result, running: false };
        return { ...m, tools };
      });
      break;

    case DONE:
      patch(id, (m) => ({ ...m, content: m.content || ev.text || "", pending: false }));
      break;

    case ERROR:
      patch(id, (m) => ({ ...m, error: ev.message, pending: false }));
      break;

    default:
      break; // 视觉类事件暂时由别的面板处理
  }
}

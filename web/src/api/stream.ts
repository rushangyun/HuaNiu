/**
 * 后端事件流的订阅层。
 *
 * 这个文件里没有任何 React、没有 UI 状态，只做一件事：
 * 把 HTTP 上的 SSE 字节流，解析成一个个 AgentEvent 对象。
 *
 * 这是"前后端解耦"落在前端的那一半——
 * 后端换框架、换语言，只要还按同一份契约推 SSE，这个文件就完全不用改。
 */

import type { AgentEvent } from "../types/events";

/** 流结束标记，必须与后端 transport/sse.py 里的一致 */
const STREAM_END = "[DONE]";

export interface ChatRequestBody {
  message: string;
  history?: Array<{ role: "user" | "assistant"; content: string }>;
}

/**
 * 发起一次对话，边收边产出事件。
 *
 * 用 fetch + ReadableStream 而不是 EventSource，
 * 因为 EventSource 只能发 GET，而对话内容要走 POST。
 */
export async function* streamChat(
  body: ChatRequestBody,
  signal?: AbortSignal
): AsyncGenerator<AgentEvent> {
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!resp.ok) {
    throw new Error(`后端返回 ${resp.status}：${(await resp.text()).slice(0, 200)}`);
  }
  if (!resp.body) {
    throw new Error("后端没有返回响应体");
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE 用空行分帧。最后一段可能不完整，留在 buffer 里等下一块数据
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;

      const payload = line.slice(5).trim();
      if (!payload) continue;
      if (payload === STREAM_END) return;

      try {
        yield JSON.parse(payload) as AgentEvent;
      } catch {
        console.warn("[stream] 解析失败，已跳过：", payload.slice(0, 120));
      }
    }
  }
}

export interface HealthStatus {
  status: string;
  llm: { base_url: string; model: string; reachable: boolean; available_models: string[] };
  vision: { available: boolean; reason: string; model_path: string };
  agent: { tools: string[]; max_rounds: number };
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthStatus> {
  const resp = await fetch("/api/health", { signal });
  if (!resp.ok) throw new Error(`健康检查失败：${resp.status}`);
  return (await resp.json()) as HealthStatus;
}

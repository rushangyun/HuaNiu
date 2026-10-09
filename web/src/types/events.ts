// 本文件由 scripts/gen_event_types.py 自动生成，**不要手改**。
// 唯一事实来源是 server/app/core/events.py，改那里之后重跑生成脚本。

// ---------------------------------------------------------------------------
// 事件类型常量（与 Python 端同名同值）
// ---------------------------------------------------------------------------

export const TOKEN = "token" as const;
export const TOOL_START = "tool_start" as const;
export const TOOL_END = "tool_end" as const;
export const ROUND = "round" as const;
export const DONE = "done" as const;
export const ERROR = "error" as const;
export const VISION_STATUS = "vision_status" as const;
export const VISION_STATS = "vision_stats" as const;

export type EventType =
  | "token" | "tool_start" | "tool_end" | "round" | "done" | "error" | "vision_status" | "vision_stats";

// ---------------------------------------------------------------------------
// 事件结构
// ---------------------------------------------------------------------------

export interface TokenEvent {
  type: typeof TOKEN;
  text?: string;
}

export interface ToolStartEvent {
  type: typeof TOOL_START;
  name?: string;
  arguments?: Record<string, unknown>;
  round?: number;
}

export interface ToolEndEvent {
  type: typeof TOOL_END;
  name?: string;
  result?: string;
  round?: number;
}

export interface RoundEvent {
  type: typeof ROUND;
  round?: number;
}

export interface DoneEvent {
  type: typeof DONE;
  text?: string;
}

export interface ErrorEvent {
  type: typeof ERROR;
  message?: string;
}

export interface VisionStatsEvent {
  type: typeof VISION_STATS;
  fps?: number;
  object_count?: number;
  elapsed_ms?: number;
}

/** 后端可能推来的任意一种事件。 */
export type AgentEvent =
  | TokenEvent
  | ToolStartEvent
  | ToolEndEvent
  | RoundEvent
  | DoneEvent
  | ErrorEvent
  | VisionStatsEvent;

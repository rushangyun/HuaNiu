/**
 * 有声书后端接口层。
 *
 * 和 api/stream.ts 同构：这里只管发请求、解析 SSE，组件不碰网络细节。
 * 所有路径都走相对路径 /api/...，由 vite 代理转发到 8000 端口的后端。
 */

// ---------------------------------------------------------------------------
// 类型
// ---------------------------------------------------------------------------
export interface SpeakerView {
  name: string;
  voice_id: string | null;
  speed: number;
  pitch: string;
}

export interface ChapterView {
  id: string;
  idx: number;
  title: string;
  status: string;
  audio_path: string | null;
  duration_sec: number | null;
}

export interface NovelSummary {
  id: string;
  title: string;
  status: string;
  char_count: number | null;
  created_at: string;
  segs: number;
}

export interface Progress {
  total: number;
  done: number;
  failed: number;
  pct: number;
}

export interface NovelDetail {
  id: string;
  title: string;
  status: string;
  char_count: number | null;
  created_at: string;
  progress: Progress;
  chapters: ChapterView[];
  speakers: SpeakerView[];
}

export interface SegmentView {
  id: string;
  chapter_id: string;
  idx: number;
  kind: string;
  speaker: string | null;
  text: string;
  raw_text: string | null;
  emotion: string | null;
  speed: number;
  pause_before_ms: number;
  status: string;
  audio_path: string | null;
  error: string | null;
}

export interface AudiobookProgress {
  novel_id: string;
  phase: string;
  done: number;
  total: number;
  failed: number;
  pct: number;
  message: string;
}

export const VOICES = [
  { id: "zh-CN-YunyangNeural", label: "云扬 · 沉稳男声（旁白）", gender: "男" },
  { id: "zh-CN-YunxiNeural", label: "云希 · 青年男声", gender: "男" },
  { id: "zh-CN-YunyeNeural", label: "云野 · 苍老男声", gender: "男" },
  { id: "zh-CN-YunjianNeural", label: "云健 · 激昂男声", gender: "男" },
  { id: "zh-CN-XiaoxiaoNeural", label: "晓晓 · 温柔女声", gender: "女" },
  { id: "zh-CN-XiaoyiNeural", label: "小艺 · 活泼女声", gender: "女" },
];

// ---------------------------------------------------------------------------
// REST
// ---------------------------------------------------------------------------
export async function createNovel(
  title: string,
  text: string,
  signal?: AbortSignal
): Promise<{ novel_id: string }> {
  const resp = await fetch("/api/novels", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, text, copyright_ack: true }),
    signal,
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function uploadNovel(
  file: File,
  signal?: AbortSignal
): Promise<{ novel_id: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("copyright_ack", "true");
  const resp = await fetch("/api/novels/upload", { method: "POST", body: form, signal });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function listNovels(signal?: AbortSignal): Promise<NovelSummary[]> {
  const resp = await fetch("/api/novels", { signal });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function getNovel(id: string, signal?: AbortSignal): Promise<NovelDetail> {
  const resp = await fetch(`/api/novels/${id}`, { signal });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function getSegments(
  id: string,
  signal?: AbortSignal
): Promise<SegmentView[]> {
  const resp = await fetch(`/api/novels/${id}/segments`, { signal });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function updateSpeaker(
  id: string,
  name: string,
  patch: { voice_id?: string | null; speed?: number; pitch?: string }
): Promise<void> {
  const resp = await fetch(`/api/novels/${id}/speakers/${encodeURIComponent(name)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!resp.ok) throw new Error(await resp.text());
}

export async function updateSegment(
  segId: string,
  patch: { speaker?: string | null; emotion?: string; speed?: number }
): Promise<void> {
  const resp = await fetch(`/api/segments/${segId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!resp.ok) throw new Error(await resp.text());
}

export async function startSynthesis(id: string): Promise<{ ok: boolean; jobs: number }> {
  const resp = await fetch(`/api/novels/${id}/synthesize`, { method: "POST" });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

/** 章节音频地址：/audio/{novelId}/chapter_{idx:02d}.mp3（由后端 /audio 静态挂载） */
export function chapterAudioUrl(novelId: string, chapterIdx: number): string {
  return `/audio/${novelId}/chapter_${String(chapterIdx).padStart(2, "0")}.mp3`;
}

/** 单段试听地址：/audio/{novelId}/seg/{segId}.mp3 */
export function segmentAudioUrl(novelId: string, segId: string): string {
  return `/audio/${novelId}/seg/${segId}.mp3`;
}

export function downloadUrl(
  novelId: string,
  scope: "book" | "chapter" | "zip",
  chapterIdx?: number
): string {
  const q = chapterIdx != null ? `&chapter_idx=${chapterIdx}` : "";
  return `/api/novels/${novelId}/download?scope=${scope}${q}`;
}

// ---------------------------------------------------------------------------
// SSE 进度订阅（和 streamStats 同构，用 EventSource 最简单）
// ---------------------------------------------------------------------------
export function subscribeProgress(
  novelId: string,
  onEvent: (p: AudiobookProgress) => void,
  signal?: AbortSignal
): EventSource {
  const es = new EventSource(`/api/novels/${novelId}/progress`);
  es.onmessage = (e) => {
    if (!e.data || e.data === "[DONE]") return;
    try {
      const data = JSON.parse(e.data);
      if (data.type === "audiobook_progress") onEvent(data as AudiobookProgress);
    } catch {
      /* 忽略心跳/非 JSON */
    }
  };
  if (signal) {
    signal.addEventListener("abort", () => es.close());
  }
  return es;
}

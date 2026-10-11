/**
 * 有声书状态 hook。
 *
 * 和 useChat / useVisionStats 同构：这一层只负责组织和订阅后端，
 * 组件层面完全是纯展示。后端事件/REST 的脏活都在 api/audiobook.ts，
 * 这里把"列表、详情、段落、进度流"拼成一个界面能直接用的最小状态。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AudiobookProgress,
  createNovel,
  getNovel,
  getSegments,
  listNovels,
  NovelDetail,
  NovelSummary,
  SegmentView,
  startSynthesis as startSynthesisApi,
  subscribeProgress,
  updateSegment,
  updateSpeaker,
  uploadNovel,
} from "../api/audiobook";

export function useAudiobook() {
  const [novels, setNovels] = useState<NovelSummary[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [detail, setDetail] = useState<NovelDetail | null>(null);
  const [segments, setSegments] = useState<SegmentView[]>([]);
  const [progress, setProgress] = useState<AudiobookProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const refreshList = useCallback(async () => {
    setNovels(await listNovels());
  }, []);

  // 首次挂载拉一下列表；卸载时关掉进度流
  useEffect(() => {
    refreshList().catch(() => {});
    return () => esRef.current?.close();
  }, [refreshList]);

  /** 打开一本书：拉详情+段落，并订阅它的进度流（解析/合成都会推） */
  const open = useCallback(async (id: string) => {
    esRef.current?.close();
    setCurrentId(id);
    setProgress(null);
    const [d, segs] = await Promise.all([getNovel(id), getSegments(id)]);
    setDetail(d);
    setSegments(segs);
    let lastPhase: string | null = d?.status ?? null;
    const refresh = () => {
      getNovel(id).then(setDetail).catch(() => {});
      getSegments(id).then(setSegments).catch(() => {});
    };
    esRef.current = subscribeProgress(id, (p) => {
      setProgress((prev) =>
        prev && prev.phase === p.phase && prev.done === p.done && prev.total === p.total
          ? prev
          : p
      );
      // 解析/合成阶段切换完成后回刷详情与段落，否则创建后界面会一直卡在「解析中」
      if (
        p.phase !== lastPhase &&
        (p.phase === "parsed" || p.phase === "done" || p.phase === "error")
      ) {
        lastPhase = p.phase;
        refresh();
      }
    });
  }, []);

  const create = useCallback(
    async (title: string, text: string) => {
      if (busy) return;
      setBusy(true);
      try {
        const { novel_id } = await createNovel(title, text);
        await refreshList();
        await open(novel_id);
      } finally {
        setBusy(false);
      }
    },
    [busy, open, refreshList]
  );

  const upload = useCallback(
    async (file: File) => {
      if (busy) return;
      setBusy(true);
      try {
        const { novel_id } = await uploadNovel(file);
        await refreshList();
        await open(novel_id);
      } finally {
        setBusy(false);
      }
    },
    [busy, open, refreshList]
  );

  /** 角色音色配置：乐观更新本地，免得每次都重拉 */
  const saveSpeaker = useCallback(
    async (name: string, patch: { voice_id?: string | null; speed?: number }) => {
      if (!currentId) return;
      await updateSpeaker(currentId, name, patch);
      setDetail((d) =>
        d
          ? {
              ...d,
              speakers: d.speakers.map((s) =>
                s.name === name ? { ...s, ...patch } : s
              ),
            }
          : d
      );
    },
    [currentId]
  );

  const saveSegment = useCallback(
    async (
      segId: string,
      patch: { speaker?: string | null; emotion?: string; speed?: number }
    ) => {
      await updateSegment(segId, patch);
      setSegments((list) =>
        list.map((s) => (s.id === segId ? { ...s, ...patch } : s))
      );
    },
    []
  );

  const startSynthesis = useCallback(async () => {
    if (!currentId || busy) return;
    setBusy(true);
    try {
      // 进度由 open() 时已订阅的 SSE 自动推动
      await startSynthesisApi(currentId);
    } finally {
      setBusy(false);
    }
  }, [currentId, busy]);

  return {
    novels,
    detail,
    segments,
    progress,
    busy,
    refreshList,
    open,
    create,
    upload,
    saveSpeaker,
    saveSegment,
    startSynthesis,
  };
}

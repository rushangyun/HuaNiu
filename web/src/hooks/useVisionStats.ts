/**
 * 订阅实时检测统计。
 *
 * 画面本身由 <img src="/api/vision/stream"> 直接显示（MJPEG），
 * 这里只订阅数字部分（帧率、目标数、单帧耗时）。
 */

import { useEffect, useState } from "react";
import { streamStats } from "../api/stream";
import { VISION_STATS, type VisionStatsEvent } from "../types/events";

export function useVisionStats(enabled: boolean) {
  const [stats, setStats] = useState<VisionStatsEvent | null>(null);

  useEffect(() => {
    // 关掉时不订阅，后端会因为没人看而自动释放摄像头
    if (!enabled) {
      setStats(null);
      return;
    }

    const controller = new AbortController();

    (async () => {
      try {
        for await (const ev of streamStats(controller.signal)) {
          if (ev.type === VISION_STATS) setStats(ev);
        }
      } catch (err) {
        if ((err as Error)?.name !== "AbortError") {
          console.warn("[vision] 统计订阅中断：", err);
        }
      }
    })();

    return () => controller.abort();
  }, [enabled]);

  return stats;
}

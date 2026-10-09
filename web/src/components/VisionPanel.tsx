/**
 * 实时检测面板。
 *
 * 画面用 <img> 直接指向 MJPEG 流，浏览器原生支持，不需要任何解码库。
 * 数字部分订阅 /api/vision/stats。
 */

import { useState } from "react";
import { useVisionStats } from "../hooks/useVisionStats";

export function VisionPanel() {
  const [on, setOn] = useState(false);
  const stats = useVisionStats(on);

  return (
    <div className="vision">
      <div className="vision-bar">
        <button onClick={() => setOn(!on)}>{on ? "关闭摄像头" : "开启摄像头"}</button>
        {on && stats && (
          <span className="vision-stats">
            {stats.fps ?? "-"} FPS · 检出 {stats.object_count ?? 0} 个 · 单帧{" "}
            {stats.elapsed_ms ?? "-"} ms
          </span>
        )}
        {on && !stats && <span className="vision-stats">正在启动…</span>}
      </div>

      {on ? (
        <img className="vision-frame" src="/api/vision/stream" alt="实时检测画面" />
      ) : (
        <div className="vision-placeholder">
          点上面的按钮开启摄像头。
          <br />
          关闭时后端会释放摄像头，指示灯会灭。
        </div>
      )}
    </div>
  );
}

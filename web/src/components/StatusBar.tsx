/** 顶栏状态点：模型服务通不通、视觉模块就绪没有。
 *
 * 它自己订阅 /api/health，父组件不用管它怎么拿数据。
 */

import { useEffect, useState } from "react";
import { fetchHealth, type HealthStatus } from "../api/stream";

export function StatusBar() {
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    const load = () =>
      fetchHealth(controller.signal)
        .then(setHealth)
        .catch(() => setHealth(null));

    load();
    // 每 20 秒探一次：视觉权重是训练完才出现的，状态会自己变
    const timer = setInterval(load, 20_000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);

  if (!health) {
    return <div className="status-dots">后端未连接</div>;
  }

  return (
    <div className="status-dots">
      <span title={`${health.llm.base_url}`}>
        <i className={`dot ${health.llm.reachable ? "ok" : "bad"}`} />
        {health.llm.model}
      </span>
      <span title={health.vision.reason}>
        <i className={`dot ${health.vision.available ? "ok" : "bad"}`} />
        视觉{health.vision.available ? "就绪" : "未就绪"}
      </span>
      <span title={health.agent.tools.join("、")}>
        {health.agent.tools.length} 个工具
      </span>
    </div>
  );
}

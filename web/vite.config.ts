import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时把 /api 转给本地后端，这样前端代码里永远写相对路径，
// 部署到别的地方只要换这里的 target（或让 nginx 代），组件不用动。
export default defineConfig({
  plugins: [react()],
  server: {
    // 显式绑 127.0.0.1：默认会只监听 IPv6 的 [::1]，
    // 结果 curl 127.0.0.1:5173 连不上，白白排查一轮
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        // SSE 是长连接，不能让代理去缓冲它，否则打字机效果会变成一次性糊出来
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            proxyRes.headers["cache-control"] = "no-cache, no-transform";
            proxyRes.headers["x-accel-buffering"] = "no";
          });
        },
      },
    },
  },
});

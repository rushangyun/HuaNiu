#!/usr/bin/env bash
# 华小牛一键启动：把 Ollama、后端、前端都拉起来，并保持常驻。
#
# 用法（在本机 Git Bash 里）：
#   ./scripts/start.sh            # 起全套
#   ./scripts/start.sh --backend  # 只起后端
#   ./scripts/start.sh --frontend # 只起前端
#
# 说明：
#   本脚本会把服务挂在 **当前终端的后台任务** 里。
#   只要这个终端窗口不关，服务就一直在；按 Ctrl+C 全部停止。
#   想关掉窗口也让服务继续，见正文第 2 节（PowerShell 的 Start-Process 方式）。
#
#   注意：本机有 http_proxy，探测本地端口必须加 --noproxy，否则会误判成"端口被占"。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_URL="http://127.0.0.1:8000"
WEB_URL="http://127.0.0.1:5173"
PROBE=(--noproxy '*' -s -m 3 -o /dev/null)

# 选 Python：优先项目虚拟环境，其次系统 python
if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"
else
  PY="python"
fi

say()  { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

up() { curl "${PROBE[@]}" -w '%{http_code}' "$1" 2>/dev/null | grep -q '^2'; }

start_backend() {
  say "[1/3] 本地大模型 Ollama"
  if up "http://127.0.0.1:11434/api/tags"; then
    ok "Ollama 已在运行"
  else
    warn "Ollama 未运行。另开一个终端执行：ollama serve"
    warn "首次使用还要拉模型：ollama pull qwen2.5:7b-instruct"
  fi

  say "[2/3] 后端 FastAPI  → $API_URL/docs"
  if up "$API_URL/health"; then
    ok "后端已在运行，跳过"
  else
    "$PY" server/main.py >> "$ROOT/server/.run.log" 2>&1 &
    echo "backend_pid=$!" >> "$ROOT/.huaniu.pids"
    for _ in $(seq 1 40); do
      sleep 1
      up "$API_URL/health" && break
    done
    up "$API_URL/health" && ok "后端已就绪" || warn "后端可能没起来，看日志：tail -f server/.run.log"
  fi
}

start_frontend() {
  say "[3/3] 前端 Vite  → $WEB_URL"
  if up "$WEB_URL"; then
    ok "前端已在运行，跳过"
  else
    (cd web && npm run dev >> "$ROOT/web/.run.log" 2>&1 &) 
    for _ in $(seq 1 40); do
      sleep 1
      up "$WEB_URL" && break
    done
    up "$WEB_URL" && ok "前端已就绪" || warn "前端可能没起来，看日志：tail -f web/.run.log"
  fi
}

rm -f "$ROOT/.huaniu.pids"

case "${1:-all}" in
  --backend)  start_backend ;;
  --frontend) start_frontend ;;
  *)          start_backend; start_frontend ;;
esac

say "完成"
echo "  对话/视觉界面：$WEB_URL"
echo "  后端接口文档：$API_URL/docs"
echo ""
echo "  这个终端别关（关了服务就停）。健康检查：./scripts/check.sh"
wait

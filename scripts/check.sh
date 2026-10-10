#!/usr/bin/env bash
# 华小牛体检：一眼看清 Ollama / 后端 / 前端是否可用，以及常见故障原因。
#
# 用法：./scripts/check.sh
#
# 注意：本机有 http_proxy，探测本地端口必须加 --noproxy '*'，
# 否则 curl 会走代理、拿到代理返回的错误页，被误判成"端口被占"。

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 注意：curl 连接失败时 -w 自己就会输出 "000"，别再额外 echo 一次，否则会变成 "000000"
probe() {
  local code
  code=$(curl --noproxy '*' -s -m 3 -o /dev/null -w '%{http_code}' "$1" 2>/dev/null)
  case "$code" in
    ''|0|000) printf '000' ;;
    *) printf '%s' "$code" ;;
  esac
}
row() {
  local name="$1" url="$2" code="$3" hint="$4"
  if [[ "$code" =~ ^2 ]]; then
    printf '  \033[32m✓\033[0m %-10s %-6s %s\n' "$name" "$code" "$url"
  else
    printf '  \033[31m✗\033[0m %-10s %-6s %s\n' "$name" "$code" "$url"
    printf '             └─ %s\n' "$hint"
  fi
}

echo "华小牛体检 — $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

code=$(probe "http://127.0.0.1:11434/api/tags")
row "Ollama" "http://127.0.0.1:11434" "$code" "没装/没起：先跑 ollama serve"

# 注意：健康检查路径是 /api/health（带 api 前缀），不是 /health
# 踩过坑：写成 /health 会返回 404，被误判成"后端没起"，其实后端活得好好的
code=$(probe "http://127.0.0.1:8000/api/health")
row "后端" "http://127.0.0.1:8000" "$code" "没起：python server/main.py（日志 server/.run.log）"

code=$(probe "http://127.0.0.1:5173")
row "前端" "http://127.0.0.1:5173" "$code" "没起：cd web && npm run dev（日志 web/.run.log）"

echo ""
echo "模型与权重："
if curl --noproxy '*' -s -m 3 "http://127.0.0.1:11434/api/tags" 2>/dev/null | grep -q 'qwen2.5'; then
  printf '  \033[32m✓\033[0m 本地模型 qwen2.5 已就位\n'
else
  printf '  \033[33m!\033[0m 没找到 qwen2.5 模型：ollama pull qwen2.5:7b-instruct\n'
fi
if [ -f "$ROOT/models/yolo/best.pt" ]; then
  printf '  \033[32m✓\033[0m 自训练权重 best.pt 存在（视觉用你自己训的模型）\n'
else
  printf '  \033[33m!\033[0m 没有 best.pt，视觉会用 COCO 预训练权重兜底（能检 80 类通用物体）\n'
fi

echo ""
echo "提示：浏览器请打开 http://127.0.0.1:5173 （用 127.0.0.1，不要用 localhost）"

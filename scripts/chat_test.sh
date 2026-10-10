#!/usr/bin/env bash
# 华小牛对话「一键诊断」—— 绕开前端，直接测后端。
#
# 用法：
#   ./scripts/chat_test.sh "算一下 12345 × 6789"
#   ./scripts/chat_test.sh "看看 server 目录下有哪些文件"
#   ./scripts/chat_test.sh "读一下 C:\Windows\System32\drivers\etc\hosts"   # 测沙箱
#
# 为什么需要它（最重要的一句）：
#   网页上看着不对劲时，先直测后端，**一次排除一半的可能性**：
#     后端返回的结果是对的 → 锅在前端，或模型「转述」时抄错了
#     后端返回的结果就错了 / 压根没调工具 → 锅在后端或 prompt，去查那边
#   不做这一步，你很容易在前端代码里白找半天，而前端其实一直是好的。
#
# 注意（本机特有的坑）：
#   本机配了 http_proxy，请求 127.0.0.1 必须绕开代理（Python 侧用 ProxyHandler({})），
#   否则会拿到代理返回的错误页，被误判成「后端挂了」。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MSG="${1:-}"
if [ -z "$MSG" ]; then
  echo "用法：./scripts/chat_test.sh \"你要问的话\""
  echo ""
  echo "例子："
  echo "  ./scripts/chat_test.sh \"算一下 12345 × 6789\""
  echo "  ./scripts/chat_test.sh \"看看 server 目录下有哪些文件\""
  echo "  ./scripts/chat_test.sh \"这个项目是干什么的\""
  exit 1
fi

# 优先用项目虚拟环境里的 python
PY="$ROOT/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="python"

"$PY" - "$MSG" <<'PYEOF'
import json
import sys
import urllib.request

msg = sys.argv[1]
url = "http://127.0.0.1:8000/api/chat"


def chat(question):
    """发一次对话，收完整的 SSE 事件流。"""
    req = urllib.request.Request(
        url,
        data=json.dumps({"message": question}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    # 关键：绕开本机代理。不这么做请求会被代理拦下，看起来像"后端挂了"。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    resp = opener.open(req, timeout=120)

    events, tokens = [], []
    for raw in resp:
        line = raw.decode("utf-8", "ignore").strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":     # 终止帧（注意不是 "done"，那是另一个事件）
            break
        try:
            ev = json.loads(payload)
        except json.JSONDecodeError:
            continue
        events.append(ev)
        if ev.get("type") == "token":
            tokens.append(ev.get("text", ""))
    return events, "".join(tokens)


try:
    events, answer = chat(msg)
except Exception as exc:                                    # noqa: BLE001
    print(f"  ✗ 请求失败：{exc}")
    print()
    print("  先确认后端在不在跑： ./scripts/check.sh")
    print("  或手动启动：        python server/main.py")
    sys.exit(1)

starts = [e for e in events if e.get("type") == "tool_start"]
ends = [e for e in events if e.get("type") == "tool_end"]
errs = [e for e in events if e.get("type") == "error"]

print()
print(f"  问：{msg}")
print("  " + "=" * 58)

if starts:
    print(f"  ① 调用工具：{len(starts)} 个")
    for e in starts:
        args = e.get("arguments") or {}
        arg_txt = " ".join(f"{k}={v}" for k, v in args.items()) if args else "（无参数）"
        print(f"       → {e.get('name')}   {arg_txt}")
else:
    print("  ① 调用工具：无   ⚠️  模型没走工具（多半是自己心算/编造了）")

if ends:
    print()
    print("  ② 工具执行结果：")
    for e in ends:
        print(f"       {e.get('name')} → {e.get('result')}")

print()
print("  ③ 模型最终回答：")
answer = answer.strip()
print(f"       {answer if answer else '（空）'}")

if errs:
    print()
    print("  ⚠️ 出错事件：")
    for e in errs:
        print(f"       {e.get('error') or e}")

print("  " + "=" * 58)
print("  怎么判断：")
print("    工具结果是对的   → 后端没问题，锅在前端或模型转述")
print("    工具结果就错了   → 后端/prompt 的问题，去查那边")
print("    压根没调工具     → prompt 引导不够，或模型偷懒")
print()
PYEOF

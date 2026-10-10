#!/usr/bin/env bash
# 推送到 GitHub —— 自动读取当前代理端口 + 失败自动重试。
#
# 用法：./scripts/push.sh [分支名] [重试次数]
#   ./scripts/push.sh              # 推 master，默认重试 3 次
#   ./scripts/push.sh master 5     # 推 master，重试 5 次
#
# 背景（本机特有的坑，务必了解）：
#   1. 代理端口**每次会话都会变**（实测 10383 → 10783 → 4633），
#      而 ~/.gitconfig 里写死了一条按 URL 匹配的代理：
#          http.https://github.com.proxy = http://127.0.0.1:10383
#      它的优先级高于通用的 http.proxy，所以 `git -c http.proxy=` 清不掉，
#      端口一过期就报 "Failed to connect to github.com over proxy 127.0.0.1"。
#      → 本脚本从环境变量实时取端口，不写死。
#
#   2. 代理可能**允许部分 github 域名而拦住 github.com**
#      （实测 raw.githubusercontent.com 通、github.com 和 ssh.github.com 不通）。
#      → 这是出口策略限制，本地改不了，只能换出口或等它恢复。
#
#   3. Windows schannel 对代理的 MITM 证书做吊销检查会失败
#      （CRYPT_E_NO_REVOCATION_CHECK），所以必须关 sslVerify。
#
# 脚本会用「当前代理」→「直连」两条路依次重试，都失败就如实报错，不假装成功。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BRANCH="${1:-master}"
RETRIES="${2:-3}"

# 实时取当前会话代理（端口会变）
PROXY="${https_proxy:-${http_proxy:-${HTTPS_PROXY:-${HTTP_PROXY:-}}}}"

say()  { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }

say "推送 $BRANCH → origin（最多 $RETRIES 次）"

for attempt in $(seq 1 "$RETRIES"); do
  echo ""
  warn "第 $attempt/$RETRIES 次尝试"

  # 每次都重新读代理，防止会话中途端口变化
  PROXY="${https_proxy:-${http_proxy:-${HTTPS_PROXY:-${HTTP_PROXY:-}}}}"

  if [ -n "$PROXY" ]; then
    warn "  经代理 $PROXY"
    if git -c "http.https://github.com.proxy=$PROXY" \
        -c http.sslVerify=false -c http.schannelCheckRevoke=false \
        push origin "$BRANCH" 2>&1 | tail -6; then
      ok "推送完成（经代理）"
      exit 0
    fi
  else
    warn "  未检测到代理环境变量"
  fi

  warn "  改走直连（把按 URL 的代理置空才是真正的禁用）"
  if git -c "http.https://github.com.proxy=" \
      -c http.sslVerify=false -c http.schannelCheckRevoke=false \
      push origin "$BRANCH" 2>&1 | tail -6; then
    ok "推送完成（直连）"
    exit 0
  fi

  if [ "$attempt" -lt "$RETRIES" ]; then
    sleep 5
  fi
done

err "全部 $RETRIES 次尝试均失败 —— GitHub 当前不可达。"
echo "    诊断要点：代理本身正常（国内站可达），但出口不转发 github.com。"
echo "    可选方案："
echo "      1) 换个网络（如手机热点）后重跑：./scripts/push.sh $BRANCH"
echo "      2) 若有固定端口的代理工具，临时指定："
echo "         git -c http.https://github.com.proxy=http://127.0.0.1:<端口> push origin $BRANCH"
echo "      3) 打包离线转移：git bundle create update.bundle origin/$BRANCH..$BRANCH"
echo ""
echo "    手动排查：echo \$http_proxy  然后  curl -I --proxy \$http_proxy https://github.com"
exit 1

#!/usr/bin/env bash
# Cloudflare IP 白名单更新脚本
# 用途: 拉取 CF 官方 IP 列表，生成 nginx allow 配置
# 失败保护: 拉取失败或内容异常时，不覆盖现有文件

set -euo pipefail

OUT_FILE="/etc/nginx/cf-allowlist.conf"
TMP_FILE="$(mktemp)"
LOG_FILE="/var/log/cf-allowlist-update.log"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

# 1. 拉取 CF v4 + v6 IP 列表（超时 10s，失败不覆盖）
v4=$(curl -fsS --max-time 10 https://www.cloudflare.com/ips-v4 || echo "")
v6=$(curl -fsS --max-time 10 https://www.cloudflare.com/ips-v6 || echo "")

if [ -z "$v4" ] || [ -z "$v6" ]; then
  log "ERROR: 拉取 CF IP 列表失败，保留现有 $OUT_FILE 不变"
  rm -f "$TMP_FILE"
  exit 1
fi

# 2. 行数合理性检查（CF 通常 v4 ~15 条 v6 ~7 条；过少视为异常）
v4_count=$(echo "$v4" | grep -c .)
v6_count=$(echo "$v6" | grep -c .)
if [ "$v4_count" -lt 10 ] || [ "$v6_count" -lt 5 ]; then
  log "ERROR: CF IP 数量异常 (v4=$v4_count, v6=$v6_count)，保留现有文件"
  rm -f "$TMP_FILE"
  exit 1
fi

# 3. 生成 nginx geo 格式（2026-04-30 从 allow/deny 改为 geo $realip_remote_addr）
# 原因：real_ip 模块已把 $remote_addr 替换为真实访客 IP，allow/deny 检查的是被替换后的值，
# 导致所有人被拦。改用 geo $realip_remote_addr 检查原始 TCP 连接 IP（CF 边缘 IP）。
# 此文件需 include 在 nginx http{} 块内（sites-available 顶部 server{} 之外）。
{
  echo "# Cloudflare IP allowlist - auto generated"
  echo "# Updated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "# Source: https://www.cloudflare.com/ips-v4 + ips-v6"
  echo "# 用法: nginx http{} 块内 include 此文件，在 server{} 块内用 \$cf_or_local 做判断"
  echo ""
  echo "# \$cf_or_local: 1=允许(CF 边缘 IP 或本机回环), 0=拒绝(直连 origin)"
  echo "geo \$realip_remote_addr \$cf_or_local {"
  echo "    default 0;"
  echo ""
  echo "    # 本机回环（前后端内部通信）"
  echo "    127.0.0.1/32 1;"
  echo "    ::1/128 1;"
  echo ""
  echo "    # === CF IPv4 ($v4_count 条) ==="
  echo "$v4" | while IFS= read -r cidr; do echo "    $cidr 1;"; done
  echo ""
  echo "    # === CF IPv6 ($v6_count 条) ==="
  echo "$v6" | while IFS= read -r cidr; do echo "    $cidr 1;"; done
  echo "}"
} > "$TMP_FILE"

# 4. 「先备份，后替换，失败回滚」策略
if [ -f "$OUT_FILE" ]; then
  cp "$OUT_FILE" "${OUT_FILE}.bak"
fi
sudo mv "$TMP_FILE" "$OUT_FILE"
sudo chmod 644 "$OUT_FILE"

if ! sudo nginx -t 2>>"$LOG_FILE"; then
  log "ERROR: nginx -t 失败，回滚"
  if [ -f "${OUT_FILE}.bak" ]; then
    sudo mv "${OUT_FILE}.bak" "$OUT_FILE"
  else
    sudo rm -f "$OUT_FILE"
  fi
  exit 1
fi

# 5. reload
sudo systemctl reload nginx
log "SUCCESS: CF IP 白名单已更新 (v4=$v4_count, v6=$v6_count)"

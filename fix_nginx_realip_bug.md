# fix_nginx_realip_bug — CF 白名单从 allow/deny 迁移到 geo $realip_remote_addr

> **执行时间**：2026-04-30 06:04–06:07 UTC  
> **备份文件**：
> - `/etc/nginx/cf-allowlist.conf.bak.20260430_060417`
> - `/etc/nginx/sites-available/miaomiaodi.cc.bak.20260430_060417`

---

## 根因回顾

`real_ip` 模块把 `$remote_addr` 替换为真实访客 IP（从 `CF-Connecting-IP` header 读取）。
旧的 `allow/deny` 指令检查的是被替换后的 `$remote_addr`（真实访客 IP），
而 CF CIDR 白名单里全是 CF 边缘 IP，两者永远不匹配，`deny all` 拦截了所有人。

---

## Step 2 改动 — update_cf_allowlist.sh 生成段 diff

```diff
-# 3. 生成 nginx 格式
+# 3. 生成 nginx geo 格式（2026-04-30 从 allow/deny 改为 geo $realip_remote_addr）
 {
   echo "# Cloudflare IP allowlist - auto generated"
   echo "# Updated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
   echo "# Source: https://www.cloudflare.com/ips-v4 + ips-v6"
-  echo ""
-  echo "# === CF IPv4 ($v4_count 条) ==="
-  echo "$v4" | while IFS= read -r cidr; do echo "allow $cidr;"; done
-  echo ""
-  echo "# === CF IPv6 ($v6_count 条) ==="
-  echo "$v6" | while IFS= read -r cidr; do echo "allow $cidr;"; done
-  echo ""
-  echo "# 本机回环（前后端通信必须保留）"
-  echo "allow 127.0.0.1;"
-  echo "allow ::1;"
-  echo ""
-  echo "# 默认拒绝"
-  echo "deny all;"
+  echo "# 用法: nginx http{} 块内 include 此文件，在 server{} 块内用\$cf_or_local做判断"
+  echo ""
+  echo "# \$cf_or_local: 1=允许(CF 边缘 IP 或本机回环), 0=拒绝(直连 origin)"
+  echo "geo \$realip_remote_addr \$cf_or_local {"
+  echo "    default 0;"
+  echo ""
+  echo "    # 本机回环（前后端内部通信）"
+  echo "    127.0.0.1/32 1;"
+  echo "    ::1/128 1;"
+  echo ""
+  echo "    # === CF IPv4 ($v4_count 条) ==="
+  echo "$v4" | while IFS= read -r cidr; do echo "    $cidr 1;"; done
+  echo ""
+  echo "    # === CF IPv6 ($v6_count 条) ==="
+  echo "$v6" | while IFS= read -r cidr; do echo "    $cidr 1;"; done
+  echo "}"
 } > "$TMP_FILE"
```

---

## Step 4 改动 — sites-available/miaomiaodi.cc diff

```diff
+# geo 定义放在 server{} 之外，被 nginx.conf http{} include 进来
+include /etc/nginx/cf-allowlist.conf;
+
 server {
     server_name miaomiaodi.cc www.miaomiaodi.cc;

     # set_real_ip_from ... (全部保留，不变)
     real_ip_header CF-Connecting-IP;
     real_ip_recursive on;

-    location ^~ /.well-known/acme-challenge/ {
-        allow all;
-        root /var/www/html;
-        try_files $uri =404;
-    }
-
-    # === CF IP 白名单 ===
-    include /etc/nginx/cf-allowlist.conf;   ← 旧：在 server{} 内，allow/deny 检查错 IP
+    # === CF 来源检查 + LE challenge 豁免（三段 set 变量法）===
+    # nginx server 级 if 比 location 匹配更早执行，无法单独用 if+location 豁免。
+    # 用三段 if 模拟"非 CF IP 且非 LE challenge → 拦截"逻辑。
+    set $block_cf 0;
+    if ($cf_or_local = 0) {
+        set $block_cf 1;
+    }
+    if ($request_uri ~* "^/.well-known/acme-challenge/") {
+        set $block_cf 0;
+    }
+    if ($block_cf = 1) {
+        return 403;
+    }
+
+    location ^~ /.well-known/acme-challenge/ {
+        root /var/www/html;
+        try_files $uri =404;
+    }

     # 其余 location 不变 ...
```

**关键设计说明**：

| 变量 | 含义 |
|------|------|
| `$realip_remote_addr` | real_ip 改写前的原始 TCP 连接 IP（CF 边缘 IP）|
| `$remote_addr` | real_ip 改写后的真实访客 IP（后端日志/限流用这个）|
| `$cf_or_local` | geo 模块定义：1=CF IP 或本机，0=直连攻击者 |
| `$block_cf` | 最终判断变量：1=拦截，0=放行 |

---

## Step 6 四项验证输出

### 6.1 经 CF 访问（正常用户）
```
HTTP/2 200
server: cloudflare
```
✅ **OK** — 正常用户经 CF 访问不受影响

### 6.2 直连 origin 绕 CF（模拟攻击者）
```
HTTP/1.1 403 Forbidden
Server: nginx
```
✅ **OK** — `$realip_remote_addr = 54.168.246.157`（服务器自身，非 CF 段）→ 拦截

### 6.3 LE challenge 路径直连
```
HTTP/1.1 404 Not Found
Server: nginx
```
✅ **OK** — 路径豁免生效（文件不存在 → 404，而非被 CF 检查拦截的 403）

### 6.4 access log remote_addr（real_ip 仍工作）
```
54.168.246.157 /
2406:da14:9de:3200:558e:857b:6619:746b /
```
✅ **OK** — 日志第一列是真实访客 IP / 请求来源，不是 CF 边缘 IP

---

## 意外情况记录

**问题**：第一版实现用单个 `if ($cf_or_local = 0) { return 403; }` 在 server 级，
LE challenge 路径直连返回 403（而非 404）。

**根因**：nginx server 级 `if` 在 rewrite phase 执行，早于 location 匹配。
`location ^~` 的高优先级只影响 location 选择阶段，无法覆盖更早的 server 级 `if return`。

**修复**：改用"三段 set 变量法"——先 `set $block_cf 1`（非 CF），
再 `if (LE challenge URI) { set $block_cf 0; }` 豁免，最后 `if ($block_cf = 1) { return 403; }`。
这是 nginx 官方认可的模拟多条件 AND/OR 的标准模式。

---

## nginx reload
`sudo systemctl reload nginx` ✅ 成功

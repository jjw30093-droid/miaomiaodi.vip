-- 2026-04-27 — admin_audit_log: 记录所有 admin 后台动作（发卡、复盘触发等）
-- 出问题可回溯 actor / IP / 入参摘要。
-- 本表不存任何秘钥（payload 仅记录 count/quota/vip_days/expire_days 数字）。

CREATE TABLE IF NOT EXISTS admin_audit_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  actor      TEXT,                              -- admin_username（来自前端 session）
  action     TEXT NOT NULL,                     -- 'generate_cdks' | 未来其他
  payload    TEXT,                              -- 入参摘要（不存秘钥）
  ip         TEXT,                              -- CF-Connecting-IP
  ua         TEXT,                              -- User-Agent 前 200 字符
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_action_time
  ON admin_audit_log(action, created_at);

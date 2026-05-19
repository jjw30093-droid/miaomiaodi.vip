/**
 * PM2 生产环境配置
 * 服务器时区: UTC（东京 ap-northeast-1）
 * 北京时间 = UTC+8，所有 cron 时间已转换为 UTC
 *
 * 每日流程:
 *   03:00 UTC (11:00 CST) → batch_fotmob_sync  : 昨日比赛数据入库
 *   04:00 UTC (12:00 CST) → fotmob_scheduler   : 爬取今明赛程写入 target_matches.json
 *   04:10 UTC (12:10 CST) → titan_odds_spider  : 获取赛程盘口赔率
 *   04:40 UTC (12:40 CST) → run_tonight        : 生成赛前研报
 *   每5分钟               → poll_lineup        : 赛前 65 分钟轮询首发
 */

const path = require('path');
const fs   = require('fs');

// ── 读取 .env ─────────────────────────────────────────────────────────────
const envFile = path.join(__dirname, '.env');
const env = {};
if (fs.existsSync(envFile)) {
  fs.readFileSync(envFile, 'utf-8').split('\n').forEach(line => {
    const m = line.match(/^([^#\s][^=]*)=(.*)$/);
    if (m) env[m[1].trim()] = m[2].trim();
  });
}

const BASE_ENV = {
  ...env,
  PYTHONUNBUFFERED: '1',
  PROJECT_ROOT: '/home/ubuntu/app/backend',
  DB_PATH:      '/home/ubuntu/app/backend/football_uk.db',
  AWS_PEM_KEY:  '/home/ubuntu/.ssh/id_rsa',
};

const PYTHON  = './venv/bin/python3';
const WORKDIR = '/home/ubuntu/app/backend';

module.exports = {
  apps: [

    // ────────────────────────────────────────────────────────────────────
    // 1. API 后端服务（常驻）
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'football-backend',
      script:         PYTHON,
      args:           'api_server.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      error_file:     '/home/ubuntu/app/backend/logs/api_server.log',
      out_file:       '/home/ubuntu/app/backend/logs/api_server.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
      restart_delay:  3000,
      max_restarts:   10,
    },

    // ────────────────────────────────────────────────────────────────────
    // 2. 前端服务（常驻）
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'football-frontend',
      script:         '/home/ubuntu/app/frontend/node_modules/.bin/next',
      args:           'start',
      cwd:            '/home/ubuntu/app/frontend',
      interpreter:    'none',
      env:            { ...BASE_ENV, PORT: '3000' },
      error_file:     '/home/ubuntu/app/backend/logs/frontend.log',
      out_file:       '/home/ubuntu/app/backend/logs/frontend.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
      restart_delay:  3000,
      max_restarts:   10,
    },

    // ────────────────────────────────────────────────────────────────────
    // 3. batch_fotmob_sync — 每天 03:00 UTC (11:00 CST)
    //    昨日赛事数据全量入库（dim_match / fact_shotmap / fact_player_match_stats）
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-batch-sync',
      script:         PYTHON,
      args:           'scripts/batch_fotmob_sync.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '0 3 * * *',   // 03:00 UTC = 11:00 CST
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/batch_sync.log',
      out_file:       '/home/ubuntu/app/backend/logs/batch_sync.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 4. fotmob_scheduler — 每天 04:00 UTC (12:00 CST)
    //    爬取今明 48 小时目标联赛赛程 → schedule/target_matches.json
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-scheduler',
      script:         PYTHON,
      args:           'fotmob_scheduler.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '0 4 * * *',   // 04:00 UTC = 12:00 CST
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/scheduler.log',
      out_file:       '/home/ubuntu/app/backend/logs/scheduler.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 5. titan_odds_spider — 每天 04:10 UTC (12:10 CST)
    //    获取 target_matches.json 中比赛的赔率数据
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-odds',
      script:         PYTHON,
      args:           'titan_odds_spider.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '10 4 * * *',  // 04:10 UTC = 12:10 CST
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/odds_spider.log',
      out_file:       '/home/ubuntu/app/backend/logs/odds_spider.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 6. run_tonight — 每天 04:40 UTC (12:40 CST)
    //    基于赔率 + 数据库生成赛前研报
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-run-tonight',
      script:         PYTHON,
      args:           'run_tonight_reports.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '40 4 * * *',  // 04:40 UTC = 12:40 CST
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/run_tonight.log',
      out_file:       '/home/ubuntu/app/backend/logs/run_tonight.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 7. poll_lineup — 每 5 分钟
    //    赛前 65 分钟开始轮询首发，确认后更新研报并推送
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-poll-lineup',
      script:         PYTHON,
      args:           'poll_lineup.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '*/5 * * * *', // 每 5 分钟
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/poll_lineup.log',
      out_file:       '/home/ubuntu/app/backend/logs/poll_lineup.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },


    // ────────────────────────────────────────────────────────────────────
    // 8. job-archiver — 每小时
    //    将开球超过2小时的比赛标记 is_archived=1，解锁赛后复盘流程
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-archiver',
      script:         PYTHON,
      args:           'archiver.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '0 * * * *',   // 每小时整点
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/archiver.log',
      out_file:       '/home/ubuntu/app/backend/logs/archiver.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 9. post-match-audit — 每天 02:00 UTC (10:00 CST)
    //    回补近 3 天已预测但未审计的比赛 WDL/OU/AH 结果（幂等，时区无关）
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-post-match-audit',
      script:         PYTHON,
      args:           'post_match_review.py --days 3',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '0 2 * * *',   // 02:00 UTC = 10:00 CST
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/post_match_audit.log',
      out_file:       '/home/ubuntu/app/backend/logs/post_match_audit.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 11. job-post-match-review — 每天 02:30 UTC (10:30 CST)
    //     在 archiver 跑完、数据入库后，生成赛后复盘 Markdown 写回 report_store
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-post-match-review',
      script:         PYTHON,
      args:           'run_post_match_reviews.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '30 2 * * *',   // 02:30 UTC = 10:30 CST
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/post_match_review_gen.log',
      out_file:       '/home/ubuntu/app/backend/logs/post_match_review_gen.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 12. closing_odds_watcher — 常驻，每 60s 扫描 T-10min 闭盘赔率
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-closing-odds-watcher',
      script:         PYTHON,
      args:           'closing_odds_watcher.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      autorestart:    true,
      max_restarts:   50,
      restart_delay:  5000,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/closing_odds_watcher.log',
      out_file:       '/home/ubuntu/app/backend/logs/closing_odds_watcher.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },
  ]
};

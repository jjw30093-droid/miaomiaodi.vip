/**
 * PM2 生产环境配置
 * 服务器时区: UTC（东京 ap-northeast-1）
 * 北京时间 = UTC+8，所有 cron 时间已转换为 UTC
 *
 * ===== 数据流依赖图（UTC = CST-8，reader 必须晚于 writer，详见 backend/CLAUDE.md §15）=====
 *   03:00  job-weekend-prefetch   FotMob → dim_match（未来7天远期赛程，不触发V1）[新增]
 *   03:00  job-batch-sync         FotMob → dim_match (scores)
 *   03:20  job-dbt-features       fact_* → dbt models
 *   03:25  job-build-lambda-features → mart_lambda_dataset_v5
 *   03:30  job-post-match-audit   dim_match → prediction_audit.actual_*
 *   03:35  job-check-recalib-trigger ← 依赖 audit
 *   03:45  job-post-match-review  dim_match + report_store → LLM 复盘
 *   04:00  job-scheduler          FotMob → target_matches.json（48h 窗口）
 *   04:00  job-daily-backtest     prediction_audit → equity_curves.json
 *   04:40  job-run-tonight        target_matches.json + report_store → 研报
 *   04:50  job-shadow-v5          schedule → shadow predictions
 *   05:00  job-shadow-cup-wdl-v5  schedule → 杯赛/欧战 WDL shadow    [新增，5/12遗失]
 *   05:30  job-pipeline-healthcheck → Server酱告警 watchdog           [新增]
 *   05:00 (Mon) job-recalibrate   prediction_audit → 校准模型
 *   05:00  job-model-snapshot     model_health_log → snapshot
 *   06:00 (Mon) job-eval-shadow-cup-wdl → shadow_cup_wdl_eval         [新增，5/12遗失]
 *
 *   每5分钟               → poll_lineup / final_lock : 赛前轮询
 *   每6小时 00:10/06:10/12:10/18:10 UTC → titan_odds_spider : 获取赔率
 *   每30分钟              → closing_odds_retry : 补抓闭盘赔率
 *   每小时                → archiver : 归档已完赛比赛
 *
 * ⚠️ 任何 cron 改动后必须运行：python3 scripts/check_cron_order.py
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
  TZ:           'UTC',                    // 显式 UTC，防子进程继承 shell 时区（CLAUDE.md §4）
  PYTHONUNBUFFERED: '1',
  PROJECT_ROOT: '/home/ubuntu/app/backend',
  DB_PATH:      '/home/ubuntu/app/backend/football_uk.db',
  AWS_PEM_KEY:  '/home/ubuntu/.ssh/LightsailDefaultKey-ap-northeast-1.pem',
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
      // ⚠️ NEXT_PUBLIC_* 变量是 Next.js build-time inline 的，写在这里对前端 bundle 无效；
      //    必须写到 frontend/.env*。本字段历史上写过 NEXT_PUBLIC_MODEL_PAGE_V2='1' 但从未生效，
      //    2026-04-27 删除 + V2 已成为 /model 的唯一渲染器。
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
    // 5. titan_odds_spider — 每 6 小时 00:10/06:10/12:10/18:10 UTC
    //    获取 target_matches.json 中比赛的赔率数据
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-odds',
      script:         PYTHON,
      args:           'titan_odds_spider.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '10 */6 * * *',  // 00:10/06:10/12:10/18:10 UTC
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/odds_spider.log',
      out_file:       '/home/ubuntu/app/backend/logs/odds_spider.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 5b. silver_builder — 每 6 小时 00:20/06:20/12:20/18:20 UTC，job-odds 之后
    //     读取 odds/match_odds_data.json → UPSERT silver_match_odds (source='nowgoal')
    //     必须在 titan_odds_spider(00:10/06:10/12:10/18:10) 完成后运行
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-silver-builder',
      script:         PYTHON,
      args:           'silver_builder.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '20 */6 * * *',   // 00:20/06:20/12:20/18:20 UTC
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/silver_builder.log',
      out_file:       '/home/ubuntu/app/backend/logs/silver_builder.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 5c. job-dbt-features — 每天 03:20 UTC (11:20 CST)，batch_sync 之后
    //     dbt rebuild int_team_match_flattened + int_team_rolling_extended
    //     + feature_engineering.py (int_team_elo_history)
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-dbt-features',
      script:         'scripts/run_daily_features.sh',
      cwd:            WORKDIR,
      interpreter:    'bash',
      env:            BASE_ENV,
      cron_restart:   '20 3 * * *',   // 03:20 UTC = 11:20 CST（batch_sync 完成后）
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/dbt_features.log',
      out_file:       '/home/ubuntu/app/backend/logs/dbt_features.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 5d. closing_odds_retry — 每 30 分钟
    //     补抓近 6h 内赛后比赛的 closing 赔率（closing_odds_watcher 漏网兜底）
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-closing-odds-retry',
      script:         PYTHON,
      args:           'scripts/closing_odds_retry.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '*/30 * * * *', // 每 30 分钟
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/closing_odds_retry.log',
      out_file:       '/home/ubuntu/app/backend/logs/closing_odds_retry.log',
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
    // 6b. job-shadow-v5 — 每天 04:50 UTC (12:50 CST)
    //     v5 A/B 影子预测补写（run_tonight 04:40 之后运行）
    //     对 prediction_audit 中尚无 v5 预测的记录写入 pred_*_v5 列
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-shadow-v5',
      script:         PYTHON,
      args:           'scripts/shadow_predict_v5.py --days 1',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '50 4 * * *',   // 04:50 UTC = 12:50 CST（run_tonight 完成后）
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/shadow_v5.log',
      out_file:       '/home/ubuntu/app/backend/logs/shadow_v5.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 6c. job-shadow-cup-wdl-v5 — 每天 05:00 UTC (13:00 CST)  [2026-05-12 新增]
    //     V5 Lambda WDL Shadow for Cup/Euro matches (UCL/UEL Phase A)
    //     ⚠️ 必须晚于 job-run-tonight (04:40)
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-shadow-cup-wdl-v5',
      script:         PYTHON,
      args:           'scripts/shadow_cup_wdl_v5.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '0 5 * * *',    // 05:00 UTC = 13:00 CST（run_tonight 04:40 之后）
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/shadow_cup_wdl_v5.log',
      out_file:       '/home/ubuntu/app/backend/logs/shadow_cup_wdl_v5.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 6d. job-eval-shadow-cup-wdl — 每周一 06:00 UTC (14:00 CST)  [2026-05-12 新增]
    //     每周 WDL 准确率评估 — shadow_cup_wdl_recs 复盘
    //     ⚠️ 必须晚于 post-match-audit (03:30)，读 actual_wdl
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-eval-shadow-cup-wdl',
      script:         PYTHON,
      args:           'scripts/eval_shadow_cup_wdl_v5.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '0 6 * * 1',   // 周一 06:00 UTC = 14:00 CST
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/eval_shadow_cup_wdl.log',
      out_file:       '/home/ubuntu/app/backend/logs/eval_shadow_cup_wdl.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 6e. job-weekend-prefetch — 每天 03:00 UTC (11:00 CST)  [2026-05-13 新增]
    //     远期赛程预抓取（未来7天），仅写 dim_match，不触发 V1 研报
    //     解决 fotmob_scheduler 48h 窗口在周中扫不到周末赛程的固有缺口
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-weekend-prefetch',
      script:         PYTHON,
      args:           'scripts/prefetch_weekend.py --days 7',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '0 3 * * *',   // 03:00 UTC = 11:00 CST（与 batch-sync 同时，不冲突）
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/weekend_prefetch.log',
      out_file:       '/home/ubuntu/app/backend/logs/weekend_prefetch.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 6f. job-pipeline-healthcheck — 每天 05:30 UTC (13:30 CST)  [2026-05-13 新增]
    //     Pipeline 健康 watchdog：检查各关键产出，失败推 Server酱
    //     晚于 run-tonight (04:40) + shadow-cup (05:00)
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-pipeline-healthcheck',
      script:         PYTHON,
      args:           'scripts/pipeline_healthcheck.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '30 5 * * *',  // 05:30 UTC = 13:30 CST
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/pipeline_healthcheck.log',
      out_file:       '/home/ubuntu/app/backend/logs/pipeline_healthcheck.log',
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
    // 8. job-final-lock — 每 5 分钟
    //    T-30±2.5min 窗口：刷新赔率 → 重算 ML/单推 → FINAL_REPORT_READY → 推云
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-final-lock',
      script:         PYTHON,
      args:           'final_lock.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '*/5 * * * *', // 每 5 分钟，命中 T-30±2.5 窗口时生效
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/final_lock.log',
      out_file:       '/home/ubuntu/app/backend/logs/final_lock.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 9. job-archiver — 每小时
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
    // 9. post-match-audit — 每天 03:30 UTC (11:30 CST)
    //    回补近 3 天已预测但未审计的比赛 WDL/OU/AH 结果（幂等，时区无关）
    //    ⚠️ 必须晚于 batch-sync (03:00)，否则 dim_match.home_score 还没写入（§15）
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-post-match-audit',
      script:         PYTHON,
      args:           'post_match_review.py --days 3',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '30 3 * * *',  // 03:30 UTC = 11:30 CST（batch-sync 之后）
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/post_match_audit.log',
      out_file:       '/home/ubuntu/app/backend/logs/post_match_audit.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 11. job-post-match-review — 每天 03:45 UTC (11:45 CST)
    //     必须在 batch_fotmob_sync(03:00) 完成后运行，否则 dim_match 无数据
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-post-match-review',
      script:         PYTHON,
      args:           'run_post_match_reviews.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '45 3 * * *',   // 03:45 UTC = 11:45 CST（batch_sync 完成后）
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/post_match_review_gen.log',
      out_file:       '/home/ubuntu/app/backend/logs/post_match_review_gen.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 模型页快照 — 每日 05:00 UTC (13:00 CST)
    // 在 job-post-match-review (03:45) + 1h15min，确保 model_health_log 已写入
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-model-snapshot',
      cwd:            '/home/ubuntu/app',
      script:         '/home/ubuntu/app/backend/venv/bin/python3',
      args:           'backend/scripts/daily_model_snapshot.py',
      autorestart:    false,
      cron_restart:   '0 5 * * *',
      error_file:     '/home/ubuntu/app/backend/logs/model_snapshot.log',
      out_file:       '/home/ubuntu/app/backend/logs/model_snapshot.log',
      merge_logs:     true,
      time:           true,
    },

    // ────────────────────────────────────────────────────────────────────
    // 12. job-daily-backtest — 每天 04:00 UTC (12:00 CST)
    //     audit 跑完后更新 equity_curves.json（必须从 /home/ubuntu/app/ 执行）
    //     ⚠️ 必须晚于 post-match-audit (03:30)，读 prediction_audit.actual_*（§15）
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-daily-backtest',
      script:         PYTHON,
      args:           'backend/scripts/daily_backtest.py',
      cwd:            '/home/ubuntu/app',
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '0 4 * * *',   // 04:00 UTC = 12:00 CST（audit 03:30 之后）
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/daily_backtest.log',
      out_file:       '/home/ubuntu/app/backend/logs/daily_backtest.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 13. job-recalibrate — 每周一 05:00 UTC (13:00 CST) 重训校准参数
    //     联赛 OU 偏置 + WDL 方向修正（约需 5 秒）
    //     ⚠️ 必须晚于 post-match-audit (03:30)，读 prediction_audit.actual_*（§15）
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-recalibrate',
      script:         PYTHON,
      args:           'recalibrate.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '0 5 * * 1',   // 每周一 05:00 UTC（audit 03:30 之后）
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/recalibrate.log',
      out_file:       '/home/ubuntu/app/backend/logs/recalibrate.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 13a. job-build-lambda-features — 每天 03:25 UTC（dbt 03:20 之后）
    //      重建 mart_lambda_dataset_v5（含未来场次 split='inference'）
    //      供 LambdaAHPredictor 在 run_tonight 04:40 时读特征行做 AH 推理
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-build-lambda-features',
      script:         'scripts/rebuild_lambda_features.sh',
      cwd:            WORKDIR,
      interpreter:    'bash',
      env:            BASE_ENV,
      cron_restart:   '25 3 * * *',  // 03:25 UTC
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/build_lambda_features.log',
      out_file:       '/home/ubuntu/app/backend/logs/build_lambda_features.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 14a. job-check-recalib-trigger — 每天 03:35 UTC（post_match_review 之后）
    //      样本数累积型自动触发：自上次 recalibrate 后已结算样本 ≥ 200
    //      → subprocess 调 `python -m recalibrate`。
    //      避免漂移裸奔（4/14~5/4 累积 289 场仍未触发的事故）。
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-check-recalib-trigger',
      script:         PYTHON,
      args:           'scripts/check_recalib_trigger.py',
      cwd:            WORKDIR,
      interpreter:    'none',
      env:            BASE_ENV,
      cron_restart:   '35 3 * * *',  // 03:35 UTC（紧贴 03:30 post-match-audit 之后）
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/check_recalib_trigger.log',
      out_file:       '/home/ubuntu/app/backend/logs/check_recalib_trigger.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 14b. job-db-backup — 每天 18:00 UTC (02:00 CST 次日)
    //      备份 football_uk.db，保留 7 天滚动，周日额外存 weekly/
    // ────────────────────────────────────────────────────────────────────
    {
      name:           'job-db-backup',
      script:         'scripts/backup_db.sh',
      cwd:            WORKDIR,
      interpreter:    'bash',
      env:            BASE_ENV,
      cron_restart:   '0 18 * * *',   // 18:00 UTC = 02:00 CST 次日
      autorestart:    false,
      watch:          false,
      error_file:     '/home/ubuntu/app/backend/logs/db_backup.log',
      out_file:       '/home/ubuntu/app/backend/logs/db_backup.log',
      log_date_format:'YYYY-MM-DD HH:mm:ss',
    },

    // ────────────────────────────────────────────────────────────────────
    // 14. closing_odds_watcher — 常驻，每 60s 扫描 T-10min 闭盘赔率
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

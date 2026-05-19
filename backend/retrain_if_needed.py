"""
retrain_if_needed.py
====================
每周自动检测模型漂移，必要时触发重训并保存新模型。

触发条件（满足任一）：
  1. 近 50 场 WDL 准确率低于漂移阈值（38%）
  2. models_v4/meta.json 中的 trained_at 距今超过 14 天

用法：
  python3 retrain_if_needed.py               # 正常运行（漂移检测 + 条件重训）
  python3 retrain_if_needed.py --force       # 强制重训，无视漂移状态
"""

import os, sys, json, argparse, logging
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = os.environ.get('PROJECT_ROOT', '/home/ubuntu/app/backend')
sys.path.insert(0, PROJECT_ROOT)

DB_PATH   = os.environ.get('DB_PATH', os.path.join(PROJECT_ROOT, 'football_uk.db'))
MODEL_DIR = os.path.join(PROJECT_ROOT, 'models_v4')

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

DRIFT_WDL_THRESHOLD = 0.38   # WDL 准确率低于此值视为漂移
RETRAIN_MAX_DAYS    = 14     # 距上次训练超过多少天强制重训


def _days_since_last_train() -> int:
    meta_path = os.path.join(MODEL_DIR, 'meta.json')
    if not os.path.exists(meta_path):
        return 999
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        trained_at = datetime.fromisoformat(meta['trained_at'])
        return (datetime.now() - trained_at).days
    except Exception as e:
        log.warning(f'读取 meta.json 失败: {e}')
        return 999


def _check_drift_status() -> dict:
    """使用 ReviewEngine 检测近期模型漂移。"""
    try:
        from review_engine import ReviewEngine
        re = ReviewEngine(DB_PATH, model_dir=MODEL_DIR)
        drift = re.check_drift()
        re.close()
        return drift
    except Exception as e:
        log.warning(f'漂移检测失败: {e}')
        return {'status': 'error', 'drift': False}


def _run_training() -> bool:
    """调用 predict_engine.ModelTrainer 进行重训。"""
    try:
        from predict_engine import ModelTrainer
        trainer = ModelTrainer(db_path=DB_PATH, model_dir=MODEL_DIR)
        success = trainer.train()
        if success:
            log.info('✅ 模型重训完成，新模型已保存至 models_v4/')
        else:
            log.error('❌ 模型重训返回失败状态')
        return success
    except Exception as e:
        log.error(f'❌ 模型重训异常: {e}', exc_info=True)
        return False


def notify_telegram(msg: str):
    """发送 Telegram 通知（如已配置 BOT_TOKEN + CHAT_ID）。"""
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat  = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat:
        return
    try:
        import urllib.request, urllib.parse
        payload = urllib.parse.urlencode({'chat_id': chat, 'text': msg}).encode()
        urllib.request.urlopen(
            f'https://api.telegram.org/bot{token}/sendMessage', payload, timeout=10
        )
    except Exception as e:
        log.warning(f'Telegram 通知失败: {e}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true', help='强制重训，忽略漂移状态')
    args = parser.parse_args()

    log.info('=' * 55)
    log.info('🔍 模型漂移检测 & 自动重训任务启动')
    log.info('=' * 55)

    # ── 1. 检查距上次训练天数 ──────────────────────────────────
    days = _days_since_last_train()
    log.info(f'📅 距上次训练: {days} 天（阈值: {RETRAIN_MAX_DAYS} 天）')

    # ── 2. 漂移检测 ───────────────────────────────────────────
    drift = _check_drift_status()
    is_drift = drift.get('drift', False)
    wdl_acc  = drift.get('wdl_acc')
    n_recent = drift.get('n', 0)

    if drift.get('status') == 'insufficient_data':
        log.info(f'⚪ 样本不足（{n_recent} 场），跳过漂移判断')
    elif is_drift:
        log.warning(f'🚨 漂移检测：近{n_recent}场 WDL准确率={wdl_acc:.1%}，低于阈值 {DRIFT_WDL_THRESHOLD:.0%}')
    else:
        log.info(f'✅ 模型状态正常，近{n_recent}场 WDL准确率={wdl_acc:.1%}' if wdl_acc else '✅ 无漂移')

    # ── 3. 决策：是否重训 ─────────────────────────────────────
    should_retrain = args.force or is_drift or (days >= RETRAIN_MAX_DAYS)

    if not should_retrain:
        log.info('ℹ️  无需重训，本次任务结束。')
        return

    reasons = []
    if args.force:         reasons.append('--force 参数')
    if is_drift:           reasons.append(f'WDL准确率={wdl_acc:.1%} 漂移')
    if days >= RETRAIN_MAX_DAYS: reasons.append(f'距上次训练 {days} 天')
    log.info(f'⚡ 触发重训，原因: {" / ".join(reasons)}')
    notify_telegram(f'🔄 喵弟量化: 模型重训开始\n原因: {", ".join(reasons)}')

    # ── 4. 执行重训 ───────────────────────────────────────────
    success = _run_training()

    if success:
        new_meta = os.path.join(MODEL_DIR, 'meta.json')
        trained_at = '未知'
        if os.path.exists(new_meta):
            try:
                trained_at = json.load(open(new_meta)).get('trained_at', '未知')
            except:
                pass
        msg = f'✅ 喵弟量化: 模型重训完成\ntrained_at: {trained_at}'
        notify_telegram(msg)
        log.info(msg)
    else:
        msg = '❌ 喵弟量化: 模型重训失败，请检查日志'
        notify_telegram(msg)
        log.error(msg)
        sys.exit(1)


if __name__ == '__main__':
    main()

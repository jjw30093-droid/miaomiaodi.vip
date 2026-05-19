"""
recalibrate.py
==============
每周一自动重训模型校准参数（pm2 cron 触发），也由
scripts/check_recalib_trigger.py（每日 03:35）按"满 N 场样本"自动触发。

1. fit_league_offsets  → 更新 calibration_league 表（联赛 OU 偏置 + 决策阈值）
2. temperature_scale   → 更新 models_v4/calibration.json（WDL 方向加法修正）
3. calibration_engine  → 重训 models_v4/calibrators.pkl（IsotonicRegression：WDL/OU/AH）
                          [2026-05-04 新增：原本游离在 cron 之外，calibrators.pkl 长期手维护漂移]

幂等安全，重复运行无副作用。
任何步骤抛异常都不阻断后续步骤——只走 ERROR + record_failure 让监控可见。
"""

import os
import sys
import logging

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main():
    log.info("=" * 50)
    log.info("🔄 开始每周校准重训...")

    # Step 1: 联赛 OU 偏置
    log.info("--- Step 1: 联赛 OU 偏置 ---")
    try:
        from calibration.fit_league_offsets import fit_and_write
        records = fit_and_write(dry_run=False)
        log.info(f"  ✅ 联赛校准写入 {len(records)} 条")
    except Exception as e:
        log.error(f"  ❌ 联赛偏置计算失败: {e}")
        import traceback; traceback.print_exc()

    # Step 2: WDL 方向修正
    log.info("--- Step 2: WDL 方向修正 ---")
    try:
        from calibration.temperature_scale import main as ts_main
        calib = ts_main(dry_run=False)
        if calib.get("status") == "ok":
            log.info(f"  ✅ WDL 校准写入: home_adj={calib['home_adj']:+.4f}")
        else:
            log.warning(f"  ⚠️ WDL 校准状态: {calib.get('status')}")
    except Exception as e:
        log.error(f"  ❌ WDL 校准失败: {e}")
        import traceback; traceback.print_exc()

    # Step 3: IsotonicRegression 校准器（calibrators.pkl）
    log.info("--- Step 3: IsotonicRegression 校准器 ---")
    calibrators_status = "skipped"
    try:
        from calibration_engine import CalibrationEngine
        ce = CalibrationEngine()
        ok = ce.train()
        calibrators_status = "ok" if ok else "failed_insufficient_data"
        if ok:
            log.info("  ✅ calibrators.pkl 已重训")
        else:
            log.warning("  ⚠️ calibrators.pkl 未更新（数据不足/预测失败）—— 见 scripts/ingest_failure_helper")
            try:
                from scripts.ingest_failure_helper import record_failure
                record_failure("recalibrate", step="calibrators_train_failed",
                               error_msg="CalibrationEngine.train() returned False")
            except Exception:
                pass
    except Exception as e:
        calibrators_status = f"exception:{type(e).__name__}"
        log.error(f"  ❌ calibrators 重训抛异常: {e}")
        import traceback; traceback.print_exc()
        try:
            from scripts.ingest_failure_helper import record_failure
            record_failure("recalibrate", step="calibrators_train_exception",
                           error_msg=f"{type(e).__name__}: {e}")
        except Exception:
            pass

    log.info(f"🏁 校准重训完成（calibrators_status={calibrators_status}）")
    log.info("=" * 50)

    # Server酱通知
    try:
        from notify_utils import notify
        notify(title="喵弟校准 · 每周重训",
               msg=f"联赛OU偏置+WDL方向修正已更新；calibrators={calibrators_status}")
    except Exception:
        pass


if __name__ == "__main__":
    main()

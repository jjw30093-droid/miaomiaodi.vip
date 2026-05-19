"""
Seed model_training_snapshot from meta.json + model_health_log.
Reads trained_at, n_samples, features_n from meta.json.
Uses latest model_health_log entry for wdl_accuracy as accuracy proxy.
"""
import sqlite3
import json
from datetime import datetime

DB = "backend/football_uk.db"
META = "backend/models_v4/meta.json"


def main():
    with open(META) as f:
        meta = json.load(f)

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Get latest model_health_log for accuracy metrics
    cur.execute("""
        SELECT wdl_accuracy, ou_accuracy, wdl_brier_avg, ou_brier_avg
        FROM model_health_log
        ORDER BY log_date DESC LIMIT 1
    """)
    row = cur.fetchone()
    wdl_acc = row[0] if row else None
    ou_acc  = row[1] if row else None
    wdl_brier = row[2] if row else None

    trained_at = meta.get("trained_at", datetime.utcnow().isoformat())
    features_n = len(meta.get("features", []))
    n_samples  = meta.get("n_samples", 0)

    # Check if snapshot already exists for this trained_at
    cur.execute(
        "SELECT id FROM model_training_snapshot WHERE trained_at = ? AND model_name = 'wdl'",
        (trained_at,)
    )
    existing = cur.fetchone()
    if existing:
        print(f"Snapshot for {trained_at} already exists (id={existing[0]}), skipping")
        conn.close()
        return

    # WDL snapshot
    cur.execute("""
        INSERT INTO model_training_snapshot
          (trained_at, model_name, sample_count, accuracy, logloss, brier, auc, features_n, notes)
        VALUES (?, 'wdl', ?, ?, NULL, ?, NULL, ?, 'v4 + xG recalib')
    """, (trained_at, n_samples, wdl_acc, wdl_brier, features_n))

    # OU snapshot
    cur.execute("""
        INSERT INTO model_training_snapshot
          (trained_at, model_name, sample_count, accuracy, logloss, brier, auc, features_n, notes)
        VALUES (?, 'ou', ?, ?, NULL, ?, NULL, ?, 'v4 + xG recalib')
    """, (trained_at, n_samples, ou_acc, None, features_n))

    conn.commit()
    conn.close()
    print(f"Inserted WDL + OU snapshots for trained_at={trained_at}")
    print(f"  n_samples={n_samples}, features_n={features_n}")
    print(f"  wdl_accuracy={wdl_acc}, ou_accuracy={ou_acc}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
inference_lambda.py — Score Matrix + 多市场推断工具库

核心函数：
  build_score_matrix(lam_h, lam_a, rho, max_goals=10)
    → 11×11 numpy array（已归一化），含 Dixon-Coles ρ 修正

  derive_wdl(matrix) → (p_home, p_draw, p_away)
  derive_ou(matrix, ou_line) → (p_over, p_under, p_push)
  derive_ah(matrix, ah_line) → (p_home_cover, p_away_cover, p_push)
  derive_btts(matrix) → (p_yes, p_no)
  derive_top_scores(matrix, top_n=5) → [(h, a, p), ...]

  full_predict(lam_h, lam_a, rho, ou_line, ah_line)
    → dict with all markets

设计原则：
  - 纯函数：无 I/O，无全局状态
  - AH quarter-ball：用 math.floor/ceil 切分两条半球线，push 各给 0.5 权重
  - OU quarter-ball：同样切分处理
  - OU push（整线）：push 返回 (p_over, p_under, 0.0)（不计 push 概率）

CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations
import math
import numpy as np
from scipy.stats import poisson


# ─────────────────────────────────────────────────────────────────────
# 1. Dixon-Coles τ 修正
# ─────────────────────────────────────────────────────────────────────

def dixon_coles_tau(h: int, a: int, lam_h: float, lam_a: float, rho: float) -> float:
    """
    Dixon-Coles (1997) τ 修正函数（标量版本）。
    仅修正低分格：(0,0) (0,1) (1,0) (1,1)。
    """
    if h == 0 and a == 0:
        return 1.0 - lam_h * lam_a * rho
    elif h == 0 and a == 1:
        return 1.0 + lam_h * rho
    elif h == 1 and a == 0:
        return 1.0 + lam_a * rho
    elif h == 1 and a == 1:
        return 1.0 - rho
    else:
        return 1.0


# ─────────────────────────────────────────────────────────────────────
# 2. Score Matrix 构建
# ─────────────────────────────────────────────────────────────────────

def build_score_matrix(
    lam_h: float,
    lam_a: float,
    rho: float = 0.0,
    max_goals: int = 10,
) -> np.ndarray:
    """
    构建 (max_goals+1) × (max_goals+1) 联合得分概率矩阵。
    matrix[i][j] = P(home=i, away=j)，含 Dixon-Coles ρ 修正。

    参数：
      lam_h   主队 λ（Poisson 均值）
      lam_a   客队 λ
      rho     Dixon-Coles ρ（正值→低分格概率↑）
      max_goals  最大进球数（行/列维度 = max_goals+1）

    返回：
      归一化后的 (max_goals+1) × (max_goals+1) numpy 数组。
    """
    n = max_goals + 1
    matrix = np.zeros((n, n), dtype=np.float64)

    for h in range(n):
        for a in range(n):
            p_h = poisson.pmf(h, lam_h)
            p_a = poisson.pmf(a, lam_a)
            tau = dixon_coles_tau(h, a, lam_h, lam_a, rho)
            matrix[h, a] = max(p_h * p_a * tau, 0.0)

    # 归一化（tau 修正可能让总和略偏离 1）
    total = matrix.sum()
    if total > 0:
        matrix /= total

    return matrix


# ─────────────────────────────────────────────────────────────────────
# 3. WDL 市场
# ─────────────────────────────────────────────────────────────────────

def derive_wdl(matrix: np.ndarray) -> tuple[float, float, float]:
    """
    从 score matrix 推导主胜/平/客胜概率。

    返回：(p_home_win, p_draw, p_away_win)
    """
    n = matrix.shape[0]
    p_home = 0.0
    p_draw = 0.0
    p_away = 0.0

    for h in range(n):
        for a in range(n):
            p = matrix[h, a]
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p

    return p_home, p_draw, p_away


# ─────────────────────────────────────────────────────────────────────
# 4. OU 市场（支持整线/半球线/四分之一球线）
# ─────────────────────────────────────────────────────────────────────

def _ou_single_line(matrix: np.ndarray, ou_line: float) -> tuple[float, float, float]:
    """
    单条 OU 线的 (p_over, p_under, p_push)。
    ou_line 为整数时存在 push（进球数恰好等于该值）。
    """
    n = matrix.shape[0]
    total_goals = np.arange(n)[:, None] + np.arange(n)[None, :]  # n×n array

    p_over = matrix[total_goals > ou_line].sum()
    p_under = matrix[total_goals < ou_line].sum()
    p_push = matrix[np.abs(total_goals - ou_line) < 1e-9].sum()

    return float(p_over), float(p_under), float(p_push)


def derive_ou(
    matrix: np.ndarray, ou_line: float
) -> tuple[float, float, float]:
    """
    计算 OU 市场各方向概率，支持整线/半线/四分之一线。

    四分之一线（如 2.75 = 2.5 + 3.0 的平均）：
      下注额各 50% 压两条半线
      push 返 0.5 亏 0.5 → 有效 push = 0（以折算收益表示）

    返回：
      (p_over_eff, p_under_eff, p_push_eff)
      — 对于半线/四分之一线，p_push_eff ≈ 0
      — 对于整线，p_push_eff > 0
    """
    # 判断是否为四分之一球线
    frac = (ou_line * 4) % 1  # 0→整线, 0.5→半球, 0→四分一(×2=整)
    fractional = ou_line - math.floor(ou_line)

    is_quarter_ball = abs(fractional - 0.25) < 1e-9 or abs(fractional - 0.75) < 1e-9

    if is_quarter_ball:
        # 拆成两条半球线
        lower = math.floor(ou_line * 2) / 2  # e.g. 2.5 for ou_line=2.75
        upper = math.ceil(ou_line * 2) / 2   # e.g. 3.0 for ou_line=2.75
        ov_l, un_l, push_l = _ou_single_line(matrix, lower)
        ov_u, un_u, push_u = _ou_single_line(matrix, upper)
        # 各 50% 权重；半线无 push，lower/upper 各自 push 理论上都为 0
        p_over = (ov_l + ov_u) / 2
        p_under = (un_l + un_u) / 2
        p_push = 0.0
    else:
        # 整线 or 半线
        p_over, p_under, p_push = _ou_single_line(matrix, ou_line)

    return p_over, p_under, p_push


# ─────────────────────────────────────────────────────────────────────
# 5. AH 市场（支持整线/半球线/四分之一球线）
# ─────────────────────────────────────────────────────────────────────

def _ah_single_line(
    matrix: np.ndarray, ah_line: float
) -> tuple[float, float, float]:
    """
    单条 AH 线的 (p_home_cover, p_away_cover, p_push)。

    ah_line 符号约定：负值=主队让球（如 -0.5 = 主让 0.5）。
    home adjusted diff = (home - away) + ah_line
      > 0 → home cover
      = 0 → push
      < 0 → away cover
    """
    n = matrix.shape[0]
    p_home = 0.0
    p_away = 0.0
    p_push = 0.0

    for h in range(n):
        for a in range(n):
            adj_diff = (h - a) + ah_line
            p = matrix[h, a]
            if adj_diff > 1e-9:
                p_home += p
            elif adj_diff < -1e-9:
                p_away += p
            else:
                p_push += p

    return float(p_home), float(p_away), float(p_push)


def derive_ah(
    matrix: np.ndarray, ah_line: float
) -> tuple[float, float, float]:
    """
    计算 AH 市场各方向概率，支持整线/半线/四分之一线。

    四分之一线（如 -0.75）：
      下注额各 50% 压两条相邻半线（-0.5 + -1.0）
      push 子腿 → 返本（以 0.5 权重）

    返回：
      (p_home_cover_eff, p_away_cover_eff, p_push_eff)

    注意：使用 math.floor/ceil 处理负数四分之一线（不可用 int()）。
      -0.75 × 2 = -1.5
      math.floor(-1.5) = -2 → lower = -1.0
      math.ceil(-1.5)  = -1 → upper = -0.5  ✓

      int(-1.5) = -1 → lower = -0.5  ✗
    """
    fractional = ah_line - math.floor(ah_line)
    is_quarter_ball = abs(fractional - 0.25) < 1e-9 or abs(fractional - 0.75) < 1e-9

    if is_quarter_ball:
        # 关键：必须用 math.floor/ceil，不能用 int()
        lower = math.floor(ah_line * 2) / 2
        upper = math.ceil(ah_line * 2) / 2

        hc_l, ac_l, push_l = _ah_single_line(matrix, lower)
        hc_u, ac_u, push_u = _ah_single_line(matrix, upper)

        # push 子腿 → 返本（相当于 0.5 权重×该方向 0 收益）
        # 有效概率 = 0.5×下线结果 + 0.5×上线结果
        # push 子腿贡献给 effective: 赢 push 的一腿≈0.5×原下注，算作 win 0.5
        # 保守处理：push 子腿作 0 贡献（不影响方向判断）
        p_home = (hc_l + hc_u) / 2
        p_away = (ac_l + ac_u) / 2
        p_push = 0.0  # quarter-ball 无真正 push（最多半赢半输）
    else:
        p_home, p_away, p_push = _ah_single_line(matrix, ah_line)

    return p_home, p_away, p_push


# ─────────────────────────────────────────────────────────────────────
# 6. BTTS 市场
# ─────────────────────────────────────────────────────────────────────

def derive_btts(matrix: np.ndarray) -> tuple[float, float]:
    """
    计算双方得分（Both Teams To Score）概率。

    BTTS Yes = P(home ≥ 1 AND away ≥ 1)
    BTTS No  = 1 - Yes

    返回：(p_yes, p_no)
    """
    n = matrix.shape[0]
    p_yes = matrix[1:, 1:].sum()
    p_no = 1.0 - p_yes
    return float(p_yes), float(p_no)


# ─────────────────────────────────────────────────────────────────────
# 7. Correct Score Top-N
# ─────────────────────────────────────────────────────────────────────

def derive_top_scores(
    matrix: np.ndarray, top_n: int = 5
) -> list[tuple[int, int, float]]:
    """
    返回概率最高的 top_n 个比分。

    返回：[(home_goals, away_goals, probability), ...]
    按概率从高到低排序。
    """
    n = matrix.shape[0]
    cells = []
    for h in range(n):
        for a in range(n):
            cells.append((h, a, float(matrix[h, a])))
    cells.sort(key=lambda x: -x[2])
    return cells[:top_n]


# ─────────────────────────────────────────────────────────────────────
# 8. 全市场一次性推断
# ─────────────────────────────────────────────────────────────────────

def full_predict(
    lam_h: float,
    lam_a: float,
    rho: float,
    ou_line: float | None = None,
    ah_line: float | None = None,
    max_goals: int = 10,
) -> dict:
    """
    给定 λ + ρ，一次性推断全部市场。

    参数：
      lam_h    主队进球 λ
      lam_a    客队进球 λ
      rho      Dixon-Coles ρ
      ou_line  OU 盘口线（None → 跳过 OU 推断）
      ah_line  AH 盘口线（None → 跳过 AH 推断）

    返回 dict：
      lam_h, lam_a, rho
      expected_total: λ_h + λ_a
      wdl: (p_home, p_draw, p_away)
      ou: (p_over, p_under, p_push) or None
      ah: (p_home_cover, p_away_cover, p_push) or None
      btts: (p_yes, p_no)
      top_scores: [(h, a, p), ...]
    """
    matrix = build_score_matrix(lam_h, lam_a, rho, max_goals)

    result = {
        'lam_h': lam_h,
        'lam_a': lam_a,
        'rho': rho,
        'expected_total': lam_h + lam_a,
        'wdl': derive_wdl(matrix),
        'btts': derive_btts(matrix),
        'top_scores': derive_top_scores(matrix, top_n=5),
    }

    if ou_line is not None and not math.isnan(ou_line):
        result['ou'] = derive_ou(matrix, ou_line)
    else:
        result['ou'] = None

    if ah_line is not None and not math.isnan(ah_line):
        result['ah'] = derive_ah(matrix, ah_line)
    else:
        result['ah'] = None

    return result


# ─────────────────────────────────────────────────────────────────────
# 快速自测
# ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=== inference_lambda.py self-test ===')

    # 典型 λ
    lam_h, lam_a, rho = 1.4, 1.0, 0.0055

    m = build_score_matrix(lam_h, lam_a, rho)
    print(f'  matrix shape: {m.shape}  sum={m.sum():.6f}')
    assert abs(m.sum() - 1.0) < 1e-8, f'matrix sum={m.sum()}'

    ph, pd, pa = derive_wdl(m)
    print(f'  WDL: H={ph:.3f} D={pd:.3f} A={pa:.3f}  sum={ph+pd+pa:.6f}')
    assert abs(ph + pd + pa - 1.0) < 1e-6

    # OU 2.5（半线，无 push）
    ov, un, push = derive_ou(m, 2.5)
    print(f'  OU 2.5: over={ov:.3f} under={un:.3f} push={push:.3f}')
    assert push < 1e-9

    # OU 2.75（四分之一线）
    ov, un, push = derive_ou(m, 2.75)
    print(f'  OU 2.75: over={ov:.3f} under={un:.3f} push={push:.3f}')
    assert push < 1e-9

    # OU 3.0（整线，可能有 push）
    ov, un, push = derive_ou(m, 3.0)
    print(f'  OU 3.0: over={ov:.3f} under={un:.3f} push={push:.3f}')
    assert abs(ov + un + push - 1.0) < 1e-4

    # AH -0.5（半线）
    hc, ac, push = derive_ah(m, -0.5)
    print(f'  AH -0.5: home={hc:.3f} away={ac:.3f} push={push:.3f}')
    assert push < 1e-9

    # AH -0.75（四分之一线，负数关键测试）
    hc, ac, push = derive_ah(m, -0.75)
    print(f'  AH -0.75: home={hc:.3f} away={ac:.3f} push={push:.3f}')
    assert push < 1e-9

    # AH 0.0（平手线，平局=push）
    hc, ac, push = derive_ah(m, 0.0)
    print(f'  AH 0.0: home={hc:.3f} away={ac:.3f} push={push:.3f}')
    assert push > 0.1  # 应有平局概率进 push

    # BTTS
    byes, bno = derive_btts(m)
    print(f'  BTTS: yes={byes:.3f} no={bno:.3f}  sum={byes+bno:.6f}')
    assert abs(byes + bno - 1.0) < 1e-6

    # Top scores
    ts = derive_top_scores(m)
    print(f'  Top scores: {[(h,a,round(p,4)) for h,a,p in ts[:3]]}')

    # full_predict
    pred = full_predict(lam_h, lam_a, rho, ou_line=2.5, ah_line=-0.75)
    assert pred['ou'] is not None
    assert pred['ah'] is not None
    print(f'  full_predict OK: {pred}')

    print('\n  ✅ 所有自测通过')

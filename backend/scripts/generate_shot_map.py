"""
generate_shot_map.py  (AWS 版)
==============================
从 football_uk.db 读取 fact_shotmap，生成 9:16 射门分布图并保存到 reports/images/。

用法：
  python3 scripts/generate_shot_map.py --match_id 4803351 --home_id 8456 --away_id 8564
  python3 scripts/generate_shot_map.py --match_id 4803351  # 自动从 dim_match 查队 ID
"""

import os, sys, argparse, sqlite3
import numpy as np
import matplotlib
matplotlib.use('Agg')   # 无头模式，AWS 无显示器
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

PROJECT_ROOT = os.environ.get('PROJECT_ROOT', '/home/ubuntu/app/backend')
DB_PATH      = os.environ.get('DB_PATH', os.path.join(PROJECT_ROOT, 'football_uk.db'))
OUTPUT_DIR   = os.path.join(PROJECT_ROOT, 'reports', 'images')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── 字体：AWS 上优先用 DejaVu，CJK 字符降级为 ASCII ──
def get_font():
    for f in ['/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
              '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']:
        if os.path.exists(f):
            return fm.FontProperties(fname=f)
    return None

CJK_FONT = get_font()

def stack_text(text):
    return '\n'.join(list(text.replace(' ', '\n')))

def load_shots(conn, match_id, team_id):
    rows = conn.execute('''
        SELECT X_Coord, Y_Coord, xG, Outcome, Player_ID
        FROM fact_shotmap
        WHERE Match_ID = ? AND Team_ID = ?
    ''', (match_id, team_id)).fetchall()
    return rows

def generate_shot_map(match_id: int, home_team_id: int = None, away_team_id: int = None,
                      home_name: str = 'Home', away_name: str = 'Away', score_text: str = '? - ?'):
    conn = sqlite3.connect(DB_PATH)

    # 自动查队 ID
    if home_team_id is None or away_team_id is None:
        dm = conn.execute(
            'SELECT Home_Team_ID, Away_Team_ID, Home_Team_Name, Away_Team_Name FROM dim_match WHERE Match_ID=?',
            (match_id,)
        ).fetchone()
        if not dm:
            print(f'❌ dim_match 中找不到 match_id={match_id}')
            conn.close()
            return None
        home_team_id = dm[0]
        away_team_id = dm[1]
        home_name    = dm[2] or home_name
        away_name    = dm[3] or away_name

    home_shots = load_shots(conn, match_id, home_team_id)
    away_shots = load_shots(conn, match_id, away_team_id)
    conn.close()

    if not home_shots and not away_shots:
        print(f'⚠️  match_id={match_id} 无射门数据，跳过')
        return None

    COLORS = {home_team_id: '#9b59b6', away_team_id: '#e74c3c'}
    Y_SHIFT = 50 - 34.38125

    try:
        from mplsoccer import VerticalPitch
        pitch = VerticalPitch(pitch_type='opta', pitch_color='white',
                              line_color='#d1d1d1', goal_type='box', linewidth=2)
        fig, ax = pitch.draw(figsize=(9, 16))
    except ImportError:
        # mplsoccer 未安装时退化到简单矩形场地
        fig, ax = plt.subplots(figsize=(9, 16))
        ax.set_xlim(0, 100); ax.set_ylim(0, 100)
        ax.set_facecolor('white')
        ax.add_patch(plt.Rectangle((0, 0), 100, 100, fill=False, edgecolor='#d1d1d1', lw=2))

    fig.set_facecolor('white')

    def plot_team(shots, team_id, is_home):
        for shot in shots:
            x_raw, y_raw, xg, outcome = shot[0], shot[1], shot[2] or 0, shot[3]
            # 主队进攻方向朝上 (X->100)；客队镜像
            x = x_raw if is_home else 100 - x_raw
            y = np.clip(y_raw + Y_SHIFT, 2, 98)
            x = np.clip(x, 2, 98)
            size   = xg * 2000 + 80
            color  = COLORS[team_id]
            is_goal = (outcome == 'Goal')
            ax.scatter(y, x, s=size,
                       edgecolors=color,
                       facecolors=color if is_goal else 'none',
                       linewidths=1.5, alpha=0.7)

    plot_team(home_shots, home_team_id, is_home=True)
    plot_team(away_shots, away_team_id, is_home=False)

    # 比分水印
    ax.text(50, 50, score_text, color='#333333', fontsize=55,
            ha='center', va='center', fontweight='bold', alpha=0.08,
            transform=ax.transData)

    # 水印
    wm_props = {'fontproperties': CJK_FONT} if CJK_FONT else {}
    ax.text(93, 85, 'MiaoMiaoDi', color='#333333',
            fontsize=14, ha='center', va='center', fontweight='bold', alpha=0.4,
            **wm_props)

    out_path = os.path.join(OUTPUT_DIR, f'shot_map_{match_id}.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f'✅ Shot map saved: {out_path}')
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--match_id',   type=int, required=True)
    parser.add_argument('--home_id',    type=int, default=None)
    parser.add_argument('--away_id',    type=int, default=None)
    parser.add_argument('--home_name',  type=str, default='Home')
    parser.add_argument('--away_name',  type=str, default='Away')
    parser.add_argument('--score',      type=str, default='? - ?',
                        help='比分字符串，如 "2 - 1"')
    args = parser.parse_args()
    generate_shot_map(args.match_id, args.home_id, args.away_id,
                      args.home_name, args.away_name, args.score)

if __name__ == '__main__':
    main()

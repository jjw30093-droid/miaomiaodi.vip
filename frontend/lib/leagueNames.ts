/**
 * 联赛名英→中翻译表（前端展示用）
 *
 * 后端数据库存的是英文 league 名（来自 FotMob），前端展示时统一中文化。
 * 所有对外渲染 league 字符串的地方（首页卡片、归档过滤器、研报详情页头）
 * 都应通过 translateLeague() 获取中文名。
 *
 * 找不到匹配时原样返回，不影响新联赛上线。
 */

const LEAGUE_NAME_ZH: Record<string, string> = {
  // 五大联赛
  'Premier League':                          '英超',
  'LaLiga':                                  '西甲',
  'Bundesliga':                              '德甲',
  'Serie A':                                 '意甲',
  'Ligue 1':                                 '法甲',

  // 欧战
  'Champions League':                        '欧冠',
  'Champions League Final Stage':            '欧冠淘汰赛',
  'Europa League':                           '欧联',
  'Europa League Final Stage':               '欧联淘汰赛',
  'Conference League':                       '欧会杯',
  'Conference League Final Stage':           '欧会杯淘汰赛',

  // 杯赛
  'FA Cup':                                  '足总杯',
  'Copa del Rey':                            '国王杯',
  'Coppa Italia':                            '意大利杯',
  'Coupe de France':                         '法国杯',
  'DFB Pokal':                               '德国杯',

  // 亚太
  // ⚠️ 'J. LEAGUE' 是历史脏数据桶（混了西甲/德甲/澳超等错标），不翻译，让它保留英文，
  //    用户在筛选下拉里能直观看出这是异常分类，避免错误归到 J联赛
  'J. League 100 Year Vision League East':   'J联赛',
  'J. League 100 Year Vision League West':   'J联赛',
  'J1':                                      'J联赛',
  'K-League 1':                              '韩K联',
  'A-League Men':                            '澳超',

  // 世界杯
  'World Cup':                               '世界杯',
  'WORLD CUP':                               '世界杯',
  'FIFA World Cup':                          '世界杯',
  'World Cup 2026':                          '世界杯',

  // 其他
  'Major Leagues':                           '主流联赛',
};

/** 英文联赛名 → 中文展示名；未匹配时原样返回 */
export function translateLeague(name: string | null | undefined): string {
  if (!name) return '';
  if (LEAGUE_NAME_ZH[name]) return LEAGUE_NAME_ZH[name];
  // 兜底：World Cup 各种大小写/后缀变体
  if (/world\s*cup/i.test(name)) return '世界杯';
  return name;
}

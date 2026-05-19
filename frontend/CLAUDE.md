@AGENTS.md

## 10. UI 重构与组件替换铁律（UI Consistency When Swapping Components）

**背景**：2026-04-18 研报页组件切换事故。为了修 VIP 分块问题，把 `<MarkdownRenderer>` 换成 `<ReportMarkdown>`，结果用户精调的字号、行高、间距全丢 —— 因为旧组件依赖 `prose` 作用域的 `prose-*` 修饰符，新组件没有 `prose` 包裹，所有修饰符静默失效。用户原话："像个半成品"。

### 10.1 1:1 样式继承（Swap = Port, Not Rewrite）
任何替换渲染组件（Markdown 渲染器、表格、Chart 包装器等）的 PR，**必须**先完成下列清单：

1. **列出旧组件所有生效的 class 源**（三个来源缺一不可）：
   - 组件内部 JSX 上的 Tailwind class
   - 父级容器上的 class（会下穿影响 `prose-*` 这类修饰符）
   - `globals.css` 里 `@utility` / `@layer` / selector 对该标签的全局样式
2. **对每个 HTML 标签（h1/h2/h3/p/ul/li/table/blockquote/code/hr）输出一张迁移表**：
   | 标签 | 旧组件类 | 新组件类 | 是否 1:1？ | 差异理由 |
3. 差异列**必须**有理由（"黑底→白底色反转"之类）。没理由就是误删。

### 10.2 禁止破坏性样式重置（No Wholesale Reset）
为了加新功能（VIP 分块、懒加载…）而**顺手**把原组件的字号、间距、字体族改掉，是**红线行为**：
- 新功能的样式只能**加**在新元素上
- 已有元素的 class **原样保留**，除非用户明确同意改
- 必须改时（如容器色反转），PR 描述里逐条列出改动点与对比截图

### 10.3 全局 9:16 适配核查（Mobile Viewport Audit）
页面结构有任何改动后，**必须**用 iPhone SE (375×667) 和 iPhone 14 Pro (393×852) 各核查一次：
- 无 `overflow-x` 横滚
- 表格/代码块不溢出卡片
- 长英文词（"Liverpool-Manchester"）有 `break-words`
- 头像、按钮在 9:16 竖屏不被挤压

三关没过，不算完工。

### 10.4 修 Bug 的守则
每个修 Bug 的 PR **必须**在描述里回答：
> "这次改动对页面视觉有哪些**非预期**的副作用？我做了哪些对照验证？"

回答 "无" 之前，先自己用 `git diff` 看一遍每一个被动过的 `.tsx` / `.css`。

### 10.5 缓存收尾承诺
所有前端改动部署后，**必须**：
1. `npm run build` 0 error
2. `pm2 restart football-frontend` 且 `pm2 logs --lines 20` 无编译错误
3. 主动提醒用户：**Cloudflare Purge Everything** + **隐私模式验证**（CF 边缘缓存和 SW 各爆过一次）

## 11. 部署目标验证铁律（Deployment Target Verification）

**背景**：2026-04 研报详情页"乌龙部署"事件。前任 agent 把 Vite 版 `dist/`
`rsync` 到 `/home/ubuntu/football_data_lake/frontend/dist/`，自信宣布"已上线"，
但 miaomiaodi.cc 实际由 **Next.js**（pm2: `football-frontend`，
`cwd=/home/ubuntu/app/frontend`）服务。Vite 那份从未触达用户。
用户整整两周以为看到的就是"设计过的页面"。

### 11.1 部署前三必查（Single Source of Truth）
任何"把 X 部署到 AWS / 生产"的任务，动手前**必须**依次跑完这三条并贴输出：

1. **pm2 认祖归宗**：
   ```bash
   pm2 describe football-frontend | grep -E 'exec cwd|script path|status'
   ```
   只认 `exec cwd` 指向的目录。任何其他 `frontend*` 目录一律视为幽灵。

2. **nginx 反代落点**：
   ```bash
   sudo nginx -T 2>/dev/null | grep -A2 'proxy_pass\|server_name miaomiaodi'
   ```
   确认 `proxy_pass` 指向 `127.0.0.1:3000`（Next.js）还是某个静态目录。

3. **domain 实响 fingerprint**：
   ```bash
   curl -sI https://miaomiaodi.cc | grep -iE 'server|x-powered-by'
   curl -s https://miaomiaodi.cc | grep -oE '_next/static|/assets/index-[a-z0-9]+\.js' | head -3
   ```
   看到 `_next/static` = Next.js；看到 `/assets/index-*.js` = Vite 构建。

**三路证据必须指向同一目录**。不一致 → 立刻停手，向用户汇报冲突。

### 11.2 禁止盲 rsync
严禁执行任何未经三必查确认的 `rsync -avz ./ host:/path/` 部署脚本。
遗留脚本（如 `deploy/deploy.sh`、`_deploy_server.sh`）里的目标路径若
与 §11.1 不一致，**以 §11.1 为准**，脚本视为过期文档，不得直接运行。

### 11.3 双前端仓库警戒
本机长期并存两份前端：
- `/home/ubuntu/football_data_lake/frontend/` — Vite + React Router（**历史参考，不上线**）
- `/home/ubuntu/app/frontend/` — Next.js 16 App Router（**生产，唯一真源**）

所有新改动只能落在后者。确需从前者移植设计时，走"**读 Vite → 手工移植 → 写 Next.js**"
流程，禁止构建 Vite 产物再往生产目录 rsync。

### 11.4 部署报告硬指标
提交"已部署"之前，必须提供以下四件套，缺一不可：
1. `pm2 restart football-frontend --update-env` 输出 + `pm2 logs --lines 30` 无 error
2. `npm run build` 0 error（在 §11.1 认定的生产目录内）
3. 隐私模式浏览器 + Cloudflare `Purge Everything` 后，对改动页面的实截图
4. 一条 `curl` 到生产域名抓到的 HTML snippet，包含本次改动的独有 class/字符串

缺任意一项，禁止宣告"完工"。

## 12. 🚨 绝对禁止：删除 `.next/` 而不立即重建（2026-04-23 事故）

**背景**：清理服务器磁盘时把 `frontend/.next/` 当"编译缓存"删掉，导致网站立刻宕机。
`football-frontend` pm2 进程虽然显示 `online`，但 `next start` 生产模式**必须有 `.next/` 才能响应请求**。

### 12.1 铁律
- **生产服务器上 `.next/` 不得删除**，除非删完立刻执行 `npm run build`
- 本地开发环境可以删（用 `next dev` 不依赖它）；**服务器绝对不行**
- 清理磁盘脚本、rsync exclude 列表、任何自动化任务，都必须把 `frontend/.next/` 列为**豁免项**

### 12.2 如果意外删了，立刻执行
```bash
cd /home/ubuntu/app/frontend
npm run build          # 约 5 分钟
pm2 restart football-frontend
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000   # 必须返回 200
```

### 12.3 永久 rsync 排除规则
本地 → 服务器同步时，**永远不要** include `.next/`：
```
--exclude='.next/'
```
服务器 → 本地拉取时，`.next/` 也没必要拉，本地用 `next dev`。


---

## 13. 🚨 用户中心（/center）已知坑与铁律（2026-04-23）

> 以下规则全部来自本次真实 bug。修改 `components/center/` 或 `app/center/page.tsx` 之前必读。

### 13.1 HeroVipCard：useState 不跟 props 联动，必须用 useEffect 同步

**背景**：`profile` 是异步从 `/user/me` 加载的。`useState(profile?.nickname)` 只读一次初始值，如果组件 mount 时 `profile` 还是 `null`（网络慢、API 失败等），昵称/头像会永远锁定在默认值 `'足球探索者'`，之后 prop 变了也不更新。

**铁律**：`HeroVipCard` 里凡是从 `profile` 初始化的 state，**必须同时配 `useEffect` 同步**：
```tsx
// ✅ 正确写法（已上线）
const [nickname, setNickname] = useState(profile?.nickname || '足球探索者');
useEffect(() => {
  if (profile?.nickname) setNickname(profile.nickname);
}, [profile?.nickname]);

const [avatarUrl, setAvatarUrl] = useState<string>(profile?.avatar_url || '');
useEffect(() => {
  if (profile?.avatar_url !== undefined) setAvatarUrl(profile.avatar_url || '');
}, [profile?.avatar_url]);
```

**反模式**：
```tsx
// ❌ 危险：profile 到来时 state 不会自动更新
const [nickname, setNickname] = useState(profile?.nickname || '足球探索者');
```

---

### 13.2 center/page.tsx：apiToken 为空时必须立即 setLoading(false)

**背景**：如果 `apiToken` 是 `undefined`，`useEffect` 提前 return，`loading` 永远不变成 `false`，页面会无限转圈。

**铁律**：
```tsx
// ✅ 正确写法（已上线）
useEffect(() => {
  if (status === 'loading') return;
  if (!apiToken) { setLoading(false); return; }  // ← 这一行不能删
  apiClient.get('/user/me', { token: apiToken })
    .then(setProfile)
    .catch(err => console.warn('[center] /user/me failed:', err?.message))
    .finally(() => setLoading(false));
}, [apiToken, status]);
```

---

### 13.3 AccountInfoCard：ROLE_DISPLAY 必须包含 'registered'

> **[过渡期现状 - 待迁移至 miaomiaodi.vip]**
> .cc 前端当前存在 VIP 角色渲染逻辑（ROLE_DISPLAY、付费分块等）。
> 按 §0 双站定位长期方向，会员体系应归 .vip，.cc 前端不应保留 VIP 概念。
> 平移完成前继续按现有逻辑维护，不要新增 VIP 相关 UI / 路由 / state。

**背景**：数据库里普通用户的 `role` 字段存的是 `'registered'`，不是 `'user'`。如果 map 里只有 `'user'`，会静默 fallback 到 `'普通用户'` 而不报错，但加新角色时容易漏。

**铁律**：
```tsx
// ✅ 正确写法（已上线）
const ROLE_DISPLAY: Record<string, string> = {
  admin: '🛡️ 管理员',
  vip: '⭐ VIP 会员',
  user: '普通用户',
  registered: '普通用户',  // ← 数据库实际存的是这个
};
```

---

### 13.4 头像上传：前端必须在发请求前校验文件大小

**背景**：nginx `client_max_body_size` 限制为 5MB（已设置），后端限制 2MB。超限时 nginx 返回 HTML 错误页，前端 `res.json()` 解析失败报 `Unexpected token '<'`，用户看到一堆乱码。

**铁律**：文件选择后，发送请求前必须先判断大小：
```tsx
// ✅ 正确写法（已上线，在 handleAvatarFile 最前面）
if (file.size > 2 * 1024 * 1024) {
  showMsg('err', '文件尺寸需小于 2MB');
  return;
}
```

---

### 13.5 头像 URL 必须用相对路径，禁止 hardcode localhost

**背景**：曾有代码写 `http://localhost:8000/static/...`，在生产环境浏览器无法访问。

**铁律**：`/static/` 路径由 nginx 反代到 FastAPI（已配置），直接用相对路径：
```tsx
// ✅ 正确
const avatarDisplay = avatarUrl || null;

// ❌ 错误：生产环境浏览器无法访问 localhost
const avatarDisplay = avatarUrl ? `http://localhost:8000${avatarUrl}` : null;
```

---

### 13.6 修改昵称的 API 路径是 /user/nickname，不是 /nickname

**背景**：曾误写成 `apiClient.patch('/nickname', ...)` → 404 Not Found，改名静默失败。

**铁律**：
```tsx
// ✅ 正确
await apiClient.patch('/user/nickname', { nickname: nicknameInput }, { token: apiToken });

// ❌ 错误：404
await apiClient.patch('/nickname', { nickname: nicknameInput }, { token: apiToken });
```

---

### 13.7 nginx 必须有 /static/ 反代块，否则头像无法访问

**背景**：FastAPI 的 `/static/` 路径（用户上传头像）若 nginx 没有对应 location，浏览器访问 404。

**已配置的 nginx 块**（`/etc/nginx/sites-available/miaomiaodi.cc`）：
```nginx
location /static/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    expires 30d;
    add_header Cache-Control "public, immutable";
}
```
**不得删除此块。** 删了头像全部 404。

同时 `/api/` 块必须有 `client_max_body_size 5m`，否则超过 1MB 的头像上传会被 nginx 截断返回 HTML 错误：
```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    ...
    client_max_body_size 5m;  # ← 不得删除
}
```

---

### 13.8 首页（app/page.tsx）：不能用 session.user.name 显示昵称

**背景**：首页曾用 `session?.user?.name` 显示用户名，该值是登录时写入 NextAuth JWT cookie 的，用户在个人中心改名后不会自动更新，导致首页昵称一直显示旧值。

**铁律**：凡是需要展示用户最新昵称/头像的页面，**必须从 `/user/me` 拉取**，不能直接用 `session.user.name` 或 `session.user.avatarUrl`：

```tsx
// ✅ 正确写法（已上线）
const apiToken = (session?.user as any)?.apiToken as string | undefined;
const [liveNickname, setLiveNickname] = useState<string>('');
const [liveAvatarUrl, setLiveAvatarUrl] = useState<string>('');

useEffect(() => {
  if (!apiToken) return;
  apiClient.get<any>('/user/me', { token: apiToken })
    .then(p => {
      if (p?.nickname) setLiveNickname(p.nickname);
      if (p?.avatar_url !== undefined) setLiveAvatarUrl(p.avatar_url || '');
    })
    .catch(() => {});
}, [apiToken]);

const displayName = liveNickname || session?.user?.name || '用户';
const avatarSrc = liveAvatarUrl || null;

// ❌ 错误：登录后不会随改名更新
const displayName = session?.user?.name || '用户';
```

---

## 14. 深浅模式：单 JSX + CSS variables / `dark:` 前缀（2026-04-23）

**背景**：历史上多个页面（`/model` Legacy、`/report/[id]` 等）把深浅主题写成了两份完整 JSX 分支（`isDark ? <DarkBlock/> : <LightBlock/>`）。结果改一套漏一套，用户原话："改了一套，另外一套也被改动了。" V2 模型页重构时彻底抛弃了这个模式。

### 14.1 铁律
新写或重构组件一律**单 JSX**，颜色切换走以下两种之一：

**A. CSS variables**（项目级 token、内联 style、ECharts 配色）
```tsx
<div style={{ background: 'var(--color-background)', color: 'var(--color-foreground)' }}>
```
已有 token 优先复用（`--color-background` / `--color-foreground` / `--primary-neon` / `--header-bg` / `--header-border` 等）；需要新 token 时在 `globals.css` 的 `:root` 和 `.dark` 两块同时定义。

**B. Tailwind `dark:` 前缀**（组件内零散 class）
```tsx
<div className="bg-white text-zinc-900 dark:bg-zinc-950 dark:text-white border-zinc-200 dark:border-zinc-800">
```

### 14.2 禁止事项（红线）
- ❌ `isDark ? <BlockA/> : <BlockB/>` 整块 JSX 分支
- ❌ 为主题复制一整段 JSX（结构/布局/文字/交互必须只写一次）
- ❌ 内联 `style={{ background: isDark ? '#000' : '#fff' }}` 三元硬编码
- ❌ 组件顶部 `const isDark = theme === 'dark'` 后在 JSX 里多处分叉

### 14.3 唯一例外：纯装饰层
仅当深浅模式要渲染**本质不同的装饰元素**（如浅色纸纹、深色 neon 光晕），允许局部条件渲染，但必须满足三条：
1. 只包裹**装饰层**（DOM 元素本身无文字、无交互、无布局承担）
2. 注释 `{/* theme-only decoration */}` 标注
3. 装饰元素外层的结构/文字/交互 JSX 依然是单份

### 14.4 ECharts 配色处理
图表组件的 option 对象不能用 `dark:` 前缀，统一从 CSS variable 读：
```tsx
const cssVar = (name: string) =>
  typeof window !== 'undefined'
    ? getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    : '';
const seriesColor = cssVar('--chart-wdl');
```
主题切换时靠 `useTheme()` hook 或监听 `<html>` class 变化的 MutationObserver 触发重渲染；禁止在 option 里 `isDark ? '#fff' : '#000'` 硬编码。

### 14.5 存量代码的处理原则：童子军规则（Boy Scout Rule）
- **不主动发起全站双 JSX refactor**——风险极高、收益分散
- **触碰哪个页面/组件，顺手把那一块统一**——改 bug 或加功能时顺手合并
- **新写的组件铁律只写一套**——从今往后禁止新增 `isDark` 双分支
- 修 bug PR 描述必答："本次改动把 N 处 `isDark` 分叉合并为单 JSX" 或 "本次未触及主题样式"

### 14.6 自查命令
提交前运行：
```bash
grep -rn "isDark ?" app/<改动目录>/ components/<改动目录>/
grep -rn "theme === 'dark'" app/<改动目录>/ components/<改动目录>/
```
改动范围内若出现新增匹配（不是改前就有的历史遗留），必须合并或走 §14.3 例外并加注释。

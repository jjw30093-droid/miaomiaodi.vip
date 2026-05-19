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

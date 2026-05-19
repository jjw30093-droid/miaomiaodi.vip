# miaomiaodi.cc — 模块 4.1 移动端 UX Audit 报告

> **性质**：只读 audit，不改任何文件  
> **执行时间**：2026-04-30  
> **方法**：curl 实测 + grep 代码扫描  
> **目标设备**：iOS Safari + 微信内置浏览器（90% 流量来自抖音手机端）

---

## § 1  Viewport Meta 实测

```bash
curl -s https://miaomiaodi.cc | grep -i "viewport|theme-color|apple-mobile"
```

**实测 SSR 输出**：

```html
<meta name="viewport" content="width=device-width, initial-scale=1">
```

| 检查项 | 结果 | 评级 |
|--------|------|------|
| viewport 是否存在 | ✅ 存在 | OK |
| maximum-scale 限制 | ✅ 无（不禁用用户缩放） | OK |
| user-scalable=no | ✅ 无 | OK |
| theme-color meta | ❌ 缺失 | P1 |
| apple-mobile-web-app-capable | ❌ 缺失 | P2 |
| manifest 链接 | ❌ 缺失 | P2 |

**Anti-FOUC 脚本**：layout.tsx 内嵌脚本读 localStorage 并注入 `dark`/`light` class，防闪烁有效。

**结论**：viewport 基础设施合格，但缺 theme-color（影响 iOS Safari 状态栏颜色）和 manifest 引用。

---

## § 2  字号体系全面扫描

### 2.1 极小字号 — CRITICAL

| 文件:行号 | 字号 | 场景 | 优先级 |
|-----------|------|------|--------|
| `app/page.tsx:107` | **text-[7px]** | 首页卡片右上角 "LIVE" 状态标签 | **P0** |
| `app/archive/page.tsx:249` | **text-[7px]** | 归档卡片右侧"含复盘"标签 | **P0** |
| `app/archive/page.tsx:254` | **text-[7px]** | 归档卡片右侧"免费"标签 | **P0** |
| `components/report/ModelVerdictCard.tsx:140` | `text-[12px]` | 研报风险提示辅助说明 | P1 |
| `components/report/MarketVsModelCard.tsx:146` | `text-[12px]` | 市场分析辅助文字 | P1 |

> 7px 在视网膜屏实际约 7pt，正常视力成年人距离 30cm 持机难以辨认，老年/视力偏弱用户完全不可读。

### 2.2 字号体系分布

| Tailwind 类 | 像素 | 出现次数 | 说明 |
|-------------|------|---------|------|
| `text-xs` | **12px** | **444** | 主要字号！用于卡片标签、联赛名、赛事时间、导航标签等大量核心文字 |
| `text-sm` | 14px | 196 | input 输入框、副标题 |
| `text-base` | 16px | 45 | 少量正文 |
| `text-lg` | 18px | 25 | 章节标题 |
| `text-xl`/`text-2xl` | 20/24px | 60 | 大标题 |

**警告**：`text-xs`（12px）作为**主要字号**出现 444 次，覆盖首页卡片联赛名、赛事时间、胜平负概率标签、导航筛选按钮等高频核心内容。WCAG AA 要求正文 ≥ 14px，Apple HIG 建议 ≥ 17pt。

**无 fluid typography**：无 `clamp()`、`min()`、`max()` 自适应字号。整体依赖固定 px。

### 2.3 Input 字号 — 🚨 iOS 自动放大 CRITICAL

**iOS Safari 规则**：input/textarea 字号 < 16px → Safari 自动放大整个页面（zoom），体验极差。

| 文件:行号 | 控件 | 字号 | 触发 iOS zoom？| 优先级 |
|-----------|------|------|----------------|--------|
| `app/register/page.tsx:86` | `<input>` 用户名 | `text-sm`（14px）| **✅ 会触发** | **P0** |
| `app/register/page.tsx:100` | `<input>` 邮箱 | `text-sm`（14px）| **✅ 会触发** | **P0** |
| `app/register/page.tsx:114` | `<input>` 密码 | `text-sm`（14px）| **✅ 会触发** | **P0** |
| `app/register/page.tsx:128` | `<input>` 确认密码 | `text-sm`（14px）| **✅ 会触发** | **P0** |
| `components/PasswordLoginCard.tsx:77` | `<input>` 用户名 | `text-sm`（14px）| **✅ 会触发** | **P0** |
| `components/PasswordLoginCard.tsx:94` | `<input>` 密码 | `text-sm`（14px）| **✅ 会触发** | **P0** |
| `components/SupportCard.tsx:57` | `<input>` 邮箱/GeekID | `text-xs`（12px）| **✅ 会触发** | **P0** |
| `components/center/HeroVipCard.tsx:152` | `<input>` 昵称编辑 | `text-[15px]` | **✅ 会触发** | **P0** |
| `components/center/RedeemCdkRow.tsx:45` | `<input>` CDK 兑换 | `text-[15px]` | **✅ 会触发** | **P0** |

> **共 9 个 input 字号 < 16px，全部触发 iOS Safari 自动放大。** 其中 CDK 兑换和昵称编辑是付费用户核心交互，破坏体验最严重。

### 2.4 三档评级汇总

**CRITICAL（< 12px，上线前必修）**

| 文件:行号 | 字号 |
|-----------|------|
| `app/page.tsx:107` | 7px |
| `app/archive/page.tsx:249,254` | 7px（×2）|

**WARNING（12-15px input / 12px 大量正文）**

| 文件:行号 | 问题 |
|-----------|------|
| `app/register/page.tsx:86,100,114,128` | input text-sm = 14px，iOS zoom |
| `components/PasswordLoginCard.tsx:77,94` | input text-sm = 14px，iOS zoom |
| `components/SupportCard.tsx:57` | input text-xs = 12px，iOS zoom |
| `components/center/HeroVipCard.tsx:152` | input text-[15px]，iOS zoom |
| `components/center/RedeemCdkRow.tsx:45` | input text-[15px]，iOS zoom |
| `app/page.tsx`（大量）| text-xs = 12px 作为核心卡片文字 |

**OK（≥ 16px）**

- `text-base`（45 处）、`text-[17px]`+（center/page.tsx）
- 主标题类 text-xl 至 text-3xl

---

## § 3  深浅色模式

### 3.1 ThemeProvider 实现

| 项目 | 现状 |
|------|------|
| 实现方式 | 自写 `ThemeProvider.tsx`（非 next-themes）|
| 默认值 | `'dark'`（硬编码）|
| **prefers-color-scheme 检测** | **❌ 完全没有** |
| 持久化 | `localStorage.setItem('theme', theme)`，key = `'theme'` |
| FOUC 防护 | ✅ layout.tsx 内联脚本 `localStorage.getItem('theme')` → 默认 `'dark'` |

**问题**：`ThemeProvider` 的 `useEffect` 仅读 `localStorage.getItem('theme')`，从不读 `window.matchMedia('(prefers-color-scheme: dark)')`。用户系统设为浅色主题时，首次访问仍强制深色，且无法"跟随系统"选项。

### 3.2 主题切换 UI

- `ThemeToggleButton` 组件出现在：首页（2处）、/model、/report/[id]（4处）、/center、/login
- 只有手动 light/dark 二选一，**无"跟随系统"第三选项**
- 切换仅影响当前会话并持久化到 localStorage

### 3.3 暗色对比度

代码层提取的主要色组（dark mode）：

| 元素 | 背景 | 前景 | 初步评估 |
|------|------|------|---------|
| 主背景 | `#09090b`（近黑）| `text-zinc-50 / white` | ✅ 高对比 |
| 卡片文字 | `bg-zinc-900` | `text-white/75~85` | ✅ 可接受 |
| 辅助文字 | — | `text-white/50`（50% 透明）| ⚠️ 灰度约 4.5:1，边缘值 |
| 极暗辅助 | — | `text-white/30`（30% 透明）| ❌ 不达 WCAG AA |
| 主题色按钮 | `#E91E63`（品红）| `text-white` | ✅ 对比通过 |

`text-white/30`（如 center/page.tsx:246 "加载中..."）在暗背景下约 2.5:1，不达 WCAG AA（4.5:1），真机验证时重点核查。

---

## § 4  响应式断点 / Layout 结构

### 4.1 断点使用频率

| 断点 | 出现次数 |
|------|---------|
| `md:` | 60 |
| `sm:` | 19 |
| `xl:` | 7 |
| `lg:` | 3 |

全站以 `max-w-md`（448px）容器居中为主要移动适配策略，响应式断点作为辅助。这种方式在手机上通常表现良好，但在宽屏上内容较窄。

### 4.2 横向溢出风险

| 文件:行号 | 宽度 | 情况 | 优先级 |
|-----------|------|------|--------|
| `components/PlayerContributionTable.tsx:150` | `min-w-[680px]` | ✅ 外层有 `overflow-x-auto` 包裹，横向滚动可接受 | OK |
| `components/HalfPitchShotMap.tsx:242` | `w-[600px] h-[600px]` | 装饰性模糊 div，使用 `-mr-64 -mt-64` 负 margin，仅视觉效果，不影响布局宽度 | OK |

无严重横向溢出 critical 问题，但 PlayerContributionTable 680px 宽表格在 375px 手机上需左右滑动，用户体验需真机验证。

### 4.3 触控目标尺寸

| 组件 | 高度 | 是否达标 Apple HIG ≥ 44pt |
|------|------|--------------------------|
| BottomNav 活跃项（`px-4 py-1.5` + icon 18px + label 13px） | ~约 44px | ✅ 接近达标 |
| BottomNav 非活跃项（`px-4 py-1.5`） | ~约 44px | ✅ |
| 主题切换按钮（`w-9 h-9`） | **36px** | ⚠️ 略小，误触率偏高 |
| 联赛筛选按钮（`py-2 text-xs`）| ~约 32px | ⚠️ 偏小 |
| 登录按钮（`py-2.5 text-sm`）| ~约 38px | ⚠️ 略小 |
| CDK 兑换确认（`py-3.5`）| ~约 48px | ✅ |
| 用户中心主操作（`h-11`）| 44px | ✅ |

### 4.4 BottomNav 安全区 — 🚨

**`env(safe-area-inset-bottom)` 完全缺失。**

```tsx
// 现状（BottomNav.tsx 深色）
<div className="fixed bottom-0 ... pb-6 ...">
  <nav className="... px-4 py-2 ...">

// 现状（BottomNav.tsx 浅色）
<nav className="fixed bottom-0 ... pb-6 pt-2">
```

iPhone X 及以后机型（包括所有全面屏 iPhone）底部 home indicator 高度约 34px。当前 `pb-6`（24px）**不足以覆盖 home indicator**，导致：
- 深色模式：悬浮胶囊 nav 被 home indicator 遮挡底部约 10px
- 浅色模式：通栏 nav `pb-6` 同样不足

正确写法：`pb-[calc(24px+env(safe-area-inset-bottom))]` 或 Tailwind `pb-safe`（需插件）

主内容区有 `pb-32`（128px）留空，内容本身不被 nav 遮挡——但 nav 本身底部被系统 indicator 挡住是视觉问题。

---

## § 5  PWA / 离线 / 主屏添加

```
public/ 目录：file.svg, globe.svg, logo_meow.jpg, favicon.ico 等
manifest.json：❌ 不存在（/manifest.json → 404）
apple-touch-icon.png：❌ 不存在
service worker：❌ 代码中无任何 serviceWorker 注册
layout.tsx manifest link：❌ 未引用
```

**现状**：完全无 PWA 支持。用户从抖音点击落地，不可收藏到主屏幕得到应用感体验。

最低成本实现（不影响现有功能）：
1. 添加 `public/apple-touch-icon.png`（180×180）
2. 添加 `public/manifest.json`（名称/图标/display=standalone）
3. layout.tsx 加 `<link rel="manifest">` 和 `<meta name="theme-color">`

---

## § 6  关键交互组件移动适配

### 6.1 Toast / 错误提示

- **实现方式**：各组件自持 `useState<string>` error 状态，在 JSX 内渲染错误文字区块
- `app/register/page.tsx:32`：直接使用 **`alert()`** 原生弹窗（"两次密码不一致"）
- 无统一 Toast 库（sonner / react-hot-toast 等）
- **移动端风险**：error 信息 div 若在 input 键盘弹起时，可能被键盘遮挡；`alert()` 在微信浏览器中会被 intercept，样式不统一

### 6.2 Modal / Drawer

- `PaywallOverlay` CDK 输入 Modal：`fixed inset-0` 全屏覆盖，有关闭按钮，基本可用
- `InteractiveShotMap`（report 页）：展开时 `document.body.style.overflow = 'hidden'` 锁定滚动 ✅
- **未发现** Drawer 组件；Modal 无 `touch-action` 控制，iOS 可能穿透滚动

### 6.3 长列表（/archive 归档）

- **分页实现**：`per_page=20`，服务端分页 ✅
- 翻页按钮在列表底部，无无限滚动
- 每条目含球队图标 `<img>`（裸标签，无 next/image），大量归档时可能有图片加载压力

### 6.4 BottomNav 安全区（已在 §4.4 详述）

缺 `env(safe-area-inset-bottom)`，iPhone 全面屏底部 nav 被 home indicator 遮挡。

---

## § 7  性能 Hint（代码层）

| 项目 | 现状 | 评级 |
|------|------|------|
| `next/image` 使用 | 12 处 import，头像/Logo 等用 Image | ✅ 部分使用 |
| 裸 `<img>` 标签 | **14 处**，主要是首页/归档/研报页球队图标 | ⚠️ P2 |
| **ECharts 懒加载** | **8 个组件同步 import（`import * as echarts`/`import ReactECharts`），无 `dynamic()`** | **⚠️ P1** |
| Framer Motion | 2 处 import | ⚠️ 低端机注意 |
| 首页 SSR 数据量 | `fetchMatches` + `fetchArchive` 两次 API 调用 | ✅ 可接受 |

**ECharts 问题详情**：
```
components/ShotMapChart.tsx      — import * as echarts
components/EChartWrapper.tsx     — import ReactECharts  
components/TacticalRadarChart.tsx — import * as echarts
components/TeamTrendChart.tsx    — import * as echarts
components/NpxgTrendChart.tsx    — import * as echarts
components/HorizontalFullPitchShotMap.tsx — import ReactECharts
components/HalfPitchShotMap.tsx  — import * as echarts
components/ShotMapScatter.tsx    — import * as echarts
```
ECharts bundle 约 1MB+，8 个组件全同步引入，研报页首次加载时间在 3G 或弱 Wi-Fi 下影响明显。应改为 `next/dynamic({ ssr: false })`。

---

## § 8  风险评级 + 修复优先级

### P0 — 上线前必修（共 12 条）

| # | 文件:行号 | 问题 | 影响场景 | 修复方向 |
|---|-----------|------|---------|---------|
| 1 | `app/page.tsx:107` | `text-[7px]` LIVE 状态标签 | 首页卡片，90% 用户 | 改 text-[10px] 或用点/色块代替文字 |
| 2 | `app/archive/page.tsx:249` | `text-[7px]` "含复盘"标签 | 归档页标签 | 同上，最小 10px |
| 3 | `app/archive/page.tsx:254` | `text-[7px]` "免费"标签 | 归档页标签 | 同上 |
| 4 | `app/register/page.tsx:86` | `<input> text-sm`（14px），iOS zoom | 注册页用户名 | 改 text-base 或 text-[16px] |
| 5 | `app/register/page.tsx:100` | `<input> text-sm`（14px），iOS zoom | 注册页邮箱 | 同上 |
| 6 | `app/register/page.tsx:114,128` | `<input> text-sm`（14px），iOS zoom | 注册页密码×2 | 同上 |
| 7 | `components/PasswordLoginCard.tsx:77` | `<input> text-sm`（14px），iOS zoom | 登录用户名 | 改 text-base |
| 8 | `components/PasswordLoginCard.tsx:94` | `<input> text-sm`（14px），iOS zoom | 登录密码 | 同上 |
| 9 | `components/SupportCard.tsx:57` | `<input> text-xs`（12px），iOS zoom | 支持页邮箱输入 | 改 text-base |
| 10 | `components/center/HeroVipCard.tsx:152` | `<input> text-[15px]`，iOS zoom | 昵称编辑（VIP 用户高频） | 改 text-[16px] |
| 11 | `components/center/RedeemCdkRow.tsx:45` | `<input> text-[15px]`，iOS zoom | CDK 兑换（付费核心） | 改 text-[16px] |
| 12 | `app/register/page.tsx:32` | `alert()`（原生弹窗）| 微信浏览器样式异常 | 改为 inline error 提示 |

### P1 — 本周（共 5 条）

| # | 文件/范围 | 问题 | 优先级 |
|---|----------|------|--------|
| 1 | `components/BottomNav.tsx` | 缺 `env(safe-area-inset-bottom)`，iPhone 全面屏底部被遮挡 | P1 |
| 2 | `app/page.tsx`（444 处 text-xs）| text-xs（12px）作为核心卡片文字（联赛名/时间/概率标签），低于推荐值 | P1 |
| 3 | `components/ThemeProvider.tsx` | 无 `prefers-color-scheme` 检测，强制深色，新用户默认无法跟随系统 | P1 |
| 4 | ECharts（8 个组件）| 同步 import，研报页 bundle 重，弱网卡顿 | P1 |
| 5 | `public/` 缺 `apple-touch-icon.png` | 用户无法在 iOS 添加主屏幕（私域留存损失） | P1 |

### P2 — 可延后（共 4 条）

| # | 问题 |
|---|------|
| 1 | 缺 PWA manifest.json + service worker（离线能力） |
| 2 | 缺 `<meta name="theme-color">`（Safari 状态栏颜色）|
| 3 | 14 处裸 `<img>` 球队图标（应换 next/image，自动 WebP + lazy）|
| 4 | 主题切换无"跟随系统"第三选项 |

---

## 最严重一条

**🚨 CDK 兑换输入框 `text-[15px]`（`RedeemCdkRow.tsx:45`）**：这是付费用户兑换 VIP 的核心操作，字号 15px 在 iOS Safari 触发自动缩放，用户刚点击输入框页面就突然放大，体验极差且会产生退款纠纷。

---

*报告生成：2026-04-30 | 下一步：等待用户决策修复顺序，执行时按 P0 → P1 → P2 顺序*

# DESIGN.md — 入乡随俗 · 风格管理 WebUI 设计系统

> 插件：`astrbot_plugin_iearning_style`（入乡随俗）
> 适用界面：`pages/style-manager/`（AstrBot Dashboard 沙箱 iframe 内嵌的插件页面）
> 设计目标：从聊天中学习并模仿他人说话方式，将学习到的风格按 **通用 / 情境 / 特定** 三层表征管理起来。
> 本文为 AI 可读的结构化设计系统，供 Cursor / Claude Code / Google Stitch 等代理在维护或扩展本界面时直接消费。

---

## 1. Visual Theme & Atmosphere

- **设计哲学**：柔和中性的现代 SaaS 风格，呼应「入乡随俗」的融入感——不炫技、不拥挤，用克制的色彩与留白让用户一眼看懂「这个群学到了什么」。
- **视觉基调**：明亮通透、层级分明、有温度（品牌渐变点缀）。
- **核心视觉特征关键词**：`三层语义色`、`卡片化`、`轻投影`、`圆角`、`图标化状态`。
- **光影与质感倾向**：纯扁平 + 微阴影（1–3 层），无拟物、无毛玻璃；强调色仅用于层级识别与关键操作。
- **品牌色**：主品牌 `#6D5EF6`（紫），搭配青绿 `#14B8A6` 与琥珀 `#F59E0B` 作为三层强调色，形成「紫/青/琥珀」三层识别体系。

---

## 2. Color Palette & Roles

所有颜色来自 CSS 变量，明/暗主题同源切换。**斜体值为暗主题覆盖**。

### Primary & Brand
| 角色 | HEX (明) | HEX (暗) | CSS 变量 | 使用场景 |
|------|----------|----------|----------|----------|
| 主品牌 | `#6D5EF6` | `#8B7EF9` | `--c-primary` | 主操作、激活态、焦点环、Logo 渐变起点 |
| 主品牌-深 | `#5B4BE0` | `#7A6CF0` | `--c-primary-600` | 主按钮 hover |
| 主品牌-浅 | `#EEEBFF` | `#232038` | `--c-primary-50` | 侧栏激活底色、输入框聚焦光晕 |

### Layer Accent（三层语义色）
| 层 | HEX (明) | HEX (暗) | CSS 变量 | 使用场景 |
|----|----------|----------|----------|----------|
| 通用 Universal | `#6366F1` | `#818CF8` | `--c-universal` | 通用 Tab / 徽章 / 条目色条 / 统计卡顶边 |
| 情境 Contextual | `#14B8A6` | `#2DD4BF` | `--c-contextual` | 情境 Tab / 徽章 / 缓冲标签 / 统计卡顶边 |
| 特定 Specific | `#F59E0B` | `#FBBF24` | `--c-specific` | 特定 Tab / 徽章 / 统计卡顶边 |

### Semantic
| 角色 | HEX | CSS 变量 | 使用场景 |
|------|------|----------|----------|
| 成功 | `#22C55E` | `--c-success` | 注入「开」状态点 |
| 警告 | `#F97316` | `--c-warning` | 脏数据横幅、错误 Toast |
| 危险 | `#EF4444` | `--c-danger` | 清空、删除、无效输入边框 |
| 信息 | `#3B82F6` | `--c-info` | 预留 |

### Neutral / Surface
| 角色 | HEX (明) | HEX (暗) | CSS 变量 |
|------|----------|----------|----------|
| 背景 | `#F5F6F8` | `#15171C` | `--c-bg` |
| 表面（卡片） | `#FFFFFF` | `#1E2128` | `--c-surface` |
| 表面-次级 | `#F0F2F5` | `#262A33` | `--c-surface-2` |
| 边框 | `#E3E6EB` | `#30353F` | `--c-border` |

### Text
| 角色 | HEX (明) | HEX (暗) | CSS 变量 |
|------|----------|----------|----------|
| 文本-主 | `#1F2329` | `#E6E8EC` | `--c-text` |
| 文本-次 | `#6B7280` | `#9AA1AC` | `--c-text-2` |
| 文本-弱 | `#9AA1AC` | `#6B7280` | `--c-text-3` |

### Shadow
| 角色 | 值 (明) | 值 (暗) | CSS 变量 |
|------|----------|----------|----------|
| 阴影-1 | `0 1px 2px rgba(16,24,40,.06)` | `0 1px 2px rgba(0,0,0,.4)` | `--sh-1` |
| 阴影-2 | `0 4px 14px rgba(16,24,40,.08)` | `0 4px 14px rgba(0,0,0,.45)` | `--sh-2` |
| 阴影-3 | `0 12px 32px rgba(16,24,40,.14)` | `0 12px 32px rgba(0,0,0,.55)` | `--sh-3` |

---

## 3. Typography Rules

- **Font Family**：`system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`
- **Mono（会话 ID / 正则）**：`ui-monospace, "JetBrains Mono", "SFMono-Regular", Consolas, monospace`

### Type Scale
| Token | 用途 | Size | Weight | Line Height | Letter Spacing |
|-------|------|------|--------|-------------|----------------|
| Display | 统计卡数字 | 26px | 700 | 1.1 | 0 |
| H1 | 品牌标题 | 15px | 600 | 1.25 | 0 |
| H2 | 区块标题 | 16px | 600 | 1.25 | 0 |
| H3 | 卡片标题 | 14px | 600 | 1.25 | 0 |
| Body | 正文（基准） | 14px | 400 | 1.5 | 0 |
| Small | 辅助/徽章 | 12px | 500 | 1.4 | 0 |
| Nano | 微标注 | 10–11px | 400 | 1.3 | 0 |

- **设计哲学**：基准 14px 保证信息密度；标题用 600 半粗建立层级；等宽字体专用于机器可读内容（会话 ID、正则）以视觉区分「数据」与「文字」；中文优先 `PingFang SC` / `Microsoft YaHei`。

---

## 4. Component Stylings

### Buttons
| 变体 | 类 | 背景 | 文字 | 边框 | 圆角 | Hover |
|------|----|------|------|------|------|-------|
| Primary | `.btn.primary` | `--c-primary` | `#fff` | `--c-primary` | 8px | `--c-primary-600` + `--sh-2` |
| Default | `.btn` | `--c-surface` | `--c-text` | `--c-border` | 8px | `--c-surface-2` |
| Ghost | `.btn.ghost` | 透明 | `--c-text-2` | 透明 | 8px | `--c-surface-2` |
| Danger | `.btn.danger` | `--c-danger` | `#fff` | `--c-danger` | 8px | `brightness(.93)` + `--sh-2` |

- 尺寸：`sm`=28px / 默认=34px；图标可左置；加载中显示 `.spin` 旋转图标并 `disabled`。
- 焦点：`:focus-visible` 显示 2px `--c-primary` 外环（offset 2px）。

### Cards / Panels
- `.panel`：背景 `--c-surface`、边框 `--c-border`、圆角 12px、阴影 `--sh-1`、头部 `.panel-head` 含强调色圆点 + 计数徽章 + 操作区。
- 脏数据态：`.panel.dirty` 显示 `.dirty-tag`（暖橙色「未保存」）。
- `.card-box`：总览区双栏卡片，同上但无头部。

### Inputs
- 文本输入：内边距 8–10px、圆角 8px、1px 边框；聚焦边框转 `--c-primary` + 4px 同色光晕（`--c-primary-50`）。
- 等宽输入：`.inp.mono`（正则）套等宽字体。
- 校验态：`.inp.invalid` 红边框 + 3px `--c-danger` 光晕。

### Navigation / Tabs
- `.tabs` 底部 1px 边框；`.tab` 圆角 2px 下划线，激活态 `--c-primary` 文字 + 下划线；左侧 8px 圆点标识所属层色。
- 侧栏会话项 `.sess`：hover `--c-surface-2`，激活态 `--c-primary-50` 底 + 3px 左侧主色条。

### Badges / Tags
- 三层计数：`<i>` 7px 圆点（层色）+ `<u>` 数字，侧栏与总览复用。
- 状态胶囊 `.chip`：1px 边框 + 圆角胶囊，含层色圆点。
- 缓冲标签 `.buf`：青绿虚线边框小标签。

### Modal / Toast
- `.overlay`：遮罩 `rgba(0,0,0,.45)`，居中 `.modal`（圆角 12px、宽 `min(360px,90vw)`、阴影 `--sh-3`、弹出动画 `pop`）。
- `.toast`：底部居中、深底白字（错误态 `--c-warning`），2.2s 淡出，`role="status"`。

---

## 5. Layout Principles

- **Spacing System**：4px 基准 —— `--s-1:4` `--s-2:8` `--s-3:12` `--s-4:16` `--s-5:20` `--s-6:24` `--s-8:32` `--s-10:40`。
- **Grid System**：内容最大宽度 1200px 居中；统计卡 4 列网格（`repeat(4,1fr)`）。
- **Container**：工作区 `.workspace` 内边距 24px（移动端 16px）；侧栏固定 282px。
- **Section Spacing**：卡片间距 20px（`--s-5`）；区块间 24px。
- **留白哲学**：卡片内边距 16–20px，条目间距 8px，靠统一节奏建立秩序；三层以色彩而非分隔线区分，减少视觉噪音。

---

## 6. Depth & Elevation

- **Shadow System**：
  - `--sh-1`：卡片静态（`0 1px 2px rgba(16,24,40,.06)`）
  - `--sh-2`：按钮 hover / 抽屉（`0 4px 14px rgba(16,24,40,.08)`）
  - `--sh-3`：弹窗 / 移动端侧栏（`0 12px 32px rgba(16,24,40,.14)`）
- **Surface Layers**：`--c-bg`（页面底）→ `--c-surface`（卡片）→ `--c-surface-2`（输入/次级底）→ `--c-border`（描边）→ 浮层（overlay/modal/toast）。
- **Z-index Scale**：内容 0 / 顶栏 30 / 脏数据横幅 25 / 侧栏抽屉 40 / 遮罩 35 / 弹窗 50 / 帮助 55 / Toast 60。
- **Backdrop Effects**：无毛玻璃；遮罩用半透明黑层叠，保持轻量。

---

## 7. Do's and Don'ts

### Do's
1. 用三层语义色（紫/青/琥珀）贯穿 Tab、徽章、条目色条、统计卡顶边，颜色即层级。
2. 任何未保存修改必须让脏数据横幅 + 面板「未保存」标记同时可见。
3. 破坏性操作（清空、丢弃）一律走确认弹窗；保存前编辑不落库。
4. 保持明/暗主题同源：所有颜色走 CSS 变量，禁止硬编码色值。
5. 移动端侧栏用抽屉（`☰` 唤出 + 遮罩），条目输入纵向堆叠。
6. 正则输入实时校验，非法立即红框并拦截保存。
7. 空状态给出插画 + 文案 + 引导按钮，降低上手门槛。

### Don'ts
1. 不要把三层用同一种颜色，避免认知负荷。
2. 不要绕开 `window.AstrBotPluginPage` 桥接直接请求后端（路由须以插件名开头）。
3. 不要在保存前把编辑写入服务器（整层保存模型，未保存即不生效）。
4. 不要用横向滚动承载窄屏列表——改为卡片化堆叠。
5. 不要伪造「最近学习时间」：后端时间戳为 `time.time()` 纪元秒，前端 `relTime` 据此换算真实相对时间；旧版本曾用单调时钟无法换算，现已统一。
6. 不要在暗主题下复用明主题描边/文本色，必须走变量切换。
7. 不要移除焦点环（`:focus-visible`），保证键盘可达。

---

## 8. Responsive Behavior

- **Breakpoints**：
  - `≥1024px`（桌面）：侧栏 282px 固定 + 工作区；Tab 完整；条目行横向输入；统计卡 4 列。
  - `768–1023px`（平板）：统计卡 2×2；总览双栏变单栏；Tab 可横向滚动。
  - `<768px`（手机）：侧栏变抽屉（`translateX` + 遮罩）；工作区满宽；Tab 分段横向滚动；条目输入纵向堆叠；统计卡 2 列；操作按钮均分。
- **Touch Targets**：按钮/可点元素 ≥ 28px，移动端关键操作 ≥ 34–44px。
- **折叠策略**：窄屏隐藏侧栏为抽屉，会话头操作按钮换行均分；`.row` 内 `.inp` 占满整行，箭头隐藏。
- **Font Scaling**：字号跟随系统；布局流式，200% 缩放下不破损（最小宽度约束 + 滚动）。
- **Reduced Motion**：`prefers-reduced-motion` 下关闭所有过渡与动画。

---

## 9. Agent Prompt Guide

### Quick Reference
- 设计令牌全部在 `pages/style-manager/styles.css` 的 `:root` 与 `html[data-theme="dark"]`。
- 页面结构在 `pages/style-manager/index.html`（语义化：`<header>`/`<aside>`/`<main>`/`<nav class="tabs">`）。
- 逻辑分层：`src/util.js`（工具）· `src/api.js`（桥接封装）· `src/store.js`（状态）· `src/views.js`（渲染+交互）· `src/app.js`（入口/路由）。
- 通信：经 `window.AstrBotPluginPage`（`ready / apiGet / apiPost`），路由以 `astrbot_plugin_iearning_style/` 开头。

### Component Prompts（可直接复制）
1. 「在 `styles.css` 中新增一个 `--c-info` 的提示条组件 `.notice`，圆角 8px、左侧 3px 信息色边、用于配置提示。」
2. 「在 `views.js` 的 `renderLayer` 中，为通用层条目的熟练度增加可编辑的数字输入框，保存时写回 `proficiency` 字段。」
3. 「给 `src/app.js` 增加批量操作：选中多个会话后一次性触发 `Api.learn`。」
4. 「在 `index.html` 增加键盘快捷键 `?` 打开帮助抽屉，并在 `onKey` 中注册。」
5. 「为情境层增加拖拽排序，更新 `store.model.contextual` 顺序并在保存时保持。」
6. 「在 `styles.css` 增加打印样式，使「导出」按钮也可打印当前会话风格画像。」

### Iteration Guide
1. 改色先改 `:root` 变量，不要在组件里硬编码，确保双主题同步。
2. 新增 API：在 `web_ui.py` 注册以插件名开头的路由，并在 `api.js` 增加对应方法，旧后端缺失时前端须优雅降级（try/catch）。
3. 新增视图：在 `views.js` 导出渲染函数，`app.js` 的 `wireEvents`/`switchTab` 接入；保持状态在 `store.js`。
4. 任何会写库的操作必须确认整层保存模型（先编辑 `store.model`，再 `Api.saveLayer`）。
5. 校验类逻辑（正则等）在客户端实时拦截 + 服务端 `_normalize_webui_entries` 二次校验，双保险。
6. 保持 `aria-label` / `role` / 焦点环，新增交互须键盘可达。
7. 移动端改动后，检查 760px 与 1023px 两个断点。
8. 不破坏既有 `snapshot` / `layer` 接口契约（前端仍依赖它们）。
9. 提交前运行 `node --check src/*.js` 做语法校验。
10. 视觉走查清单：双主题对比度、焦点环、空态、Toast、Modal 焦点陷阱、窄屏抽屉。

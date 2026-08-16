# 风格管理 WebUI 重构概览

> 插件：`astrbot_plugin_iearning_style`（入乡随俗）
> 重构日期：2026-08-16
> 目标：彻底重构前端架构与视觉布局，提升美观度、流畅性与响应式适配，与插件功能深度契合且易于维护扩展，原有核心功能完整可用。

## 改动清单

### 1. 前端架构重构（核心）
将原有单文件 `app.js` 拆分为分层模块，单一数据源 + 视图/交互分离：

| 文件 | 职责 |
|------|------|
| `pages/style-manager/index.html` | 语义化结构：顶栏 / 脏数据横幅 / 会话侧栏 / 工作区 Tab / 弹窗 / 帮助抽屉 |
| `pages/style-manager/styles.css` | 完整设计令牌（Design Tokens）+ 组件样式，明/暗双主题同源 |
| `pages/style-manager/src/util.js` | DOM 工具、Toast、确认弹窗、正则校验、主题 |
| `pages/style-manager/src/api.js` | `window.AstrBotPluginPage` 桥接封装（snapshot/stats/layer/learn/clear/export） |
| `pages/style-manager/src/store.js` | 中央状态（单一数据源）+ 派生计算 |
| `pages/style-manager/src/views.js` | 视图渲染与局部交互（侧栏/总览/层编辑/会话操作） |
| `pages/style-manager/src/app.js` | 入口：桥接初始化、全局事件、Tab 路由 |

### 2. 新增交互能力（对应设计稿）
- **总览 Tab**：统计卡（总条目/各层数量/注入状态/各层容量）+ 风格画像（注入预览）+ Top 梗榜。
- **会话级操作**：立即学习 / 清空本会话 / 导出 JSON（移至界面，等价于聊天命令）。
- **防丢失**：顶部脏数据横幅（保存全部/丢弃）+ 切换/刷新确认。
- **层内检索**、**正则实时校验**、熟练度进度条、缓冲位标记。
- **明/暗主题**切换（持久化）、**移动端抽屉式侧栏**、快捷键（`/` 搜索 · `Ctrl/⌘+S` 保存 · `Esc` 关闭）。

### 3. 后端扩展（向后兼容，旧接口不变）
- `learning_style/data_manager.py`：新增 `global_stats()` / `clear_session()` / `export_session()`。
- `learning_style/web_ui.py`：注册 `/stats` `/learn` `/clear` `/export` 路由，接入 `learning_manager`。
- `main.py`：向 `StylePage` 传入 `learning_manager`。
- 原有 `GET /snapshot` 与 `POST /layer` 完全保留；新接口在旧后端缺失时前端自动降级（提示用聊天命令）。

### 4. 设计文档
- 新增根目录 `DESIGN.md`：awesome-design-md 9 章节标准设计系统，供 AI 代理维护时直接消费。
- `README.md` 的「风格管理页面」章节已更新为重构后说明。

## 验证
- Python：`py_compile` 通过（`data_manager.py` / `web_ui.py` / `main.py`）。
- 前端：5 个 JS 模块 `node --check` 通过。
- 运行时：基于 jsdom + mock 桥接的冒烟测试 11 项全过（启动渲染、会话切换、Tab 切换、编辑脏数据、保存调用 `layer`、立即学习调用 `learn`、正则实时校验等）。

## 使用方式
1. 在 AstrBot 面板：**扩展 → 插件详情 → 打开插件页面**（需 v4.26+）。
2. 左侧选会话 → 总览看全局 → 三层 Tab 编辑 → 「保存本层」生效。
3. 顶部按钮：刷新 / 主题 / 帮助；会话头：立即学习 / 导出 / 清空。

## 注意事项
- 后端存储的时间戳已统一为 `time.time()` 纪元秒（旧版本曾用 asyncio 单调时钟，无法换算真实时间）。
- 若后端为旧版本（未注册这些接口），界面会自动降级——这些按钮点击时会提示「请到聊天中发送对应命令」，不影响三层查看与编辑。

## v1.1.1 三要素优化（2026-08-16）

在不丢失任何功能的前提下，按可维护/最轻量/高质量三要素进行了系统优化：

**可维护性**
- 删除并存的两套前端（旧 `pages/style-manager/app.js`），仅保留模块化 `src/` 版本；归档 `design/prototype/` 到 `_archive/`。
- `DataManager` 瘦身：将 81 行 WebUI 归一化逻辑抽离到 `web_ui.py:normalize_webui_entries`，存储层职责单一。
- 散弹式 `asyncio.create_task(self._schedule_save())`（9 处）收敛为统一入口 `_mark_dirty_and_schedule(layer)`。

**最轻量**
- 死字段复活：启用 `trigger_regex` 按用户消息命中注入（原本「存了不用」），特定层按需注入、prompt 不膨胀。
- `difflib` 情境合并加配置开关 `enable_contextual_merge`（默认 true，可关）。
- `replace_layer` 从 26 行降至 ~15 行。

**高质量**
- 修复 `_schedule_save` race：旧版「cancel 后就忘」会丢失连续 mark_dirty 的数据；新版 await 旧 task 终止 + `_delayed_save` 重检 dirty。
- 前端 XSS 修复：`util.js:esc` 真转义 `&<>"'`，portrait/Top 梗榜改 `textContent`。
- JSON 提取鲁棒化：`learning_manager._extract_json` 括号配平扫描，正确处理嵌套对象、字符串内大括号、尾随解释。
- 旧格式迁移补全：`_handle_old_format` 真迁移 `styles.json` 到 universal 层（旧版仅 rename 导致数据丢失）。
- ReDoS 防护：`add_or_update_specific` 限制正则长度 ≤200、拒绝嵌套量词；注入时超长消息(>10000)不匹配。
- 测试基线：`tests/` 下 pytest 25 项（覆盖边界/race/迁移/ReDoS/JSON 提取）。

详细方案见 `OPTIMIZATION_PLAN.md`；维护约定见 `AGENTS.md`。

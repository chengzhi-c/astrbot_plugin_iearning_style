# AGENTS.md — 入乡随俗插件维护约定

## 3-Agent System

### Planner (lazy senior dev)
- 决策阶梯：YAGNI → 复用 → stdlib → 平台 → 依赖 → 一行 → 最小代码。
- 修 root cause，不修 symptom：先搜全 callers，再改共享函数。
- 最小 diff，无 scope expansion，无未请求抽象。

### Worker (execution-only)
- 仅执行任务，产 patch，不做设计决策。
- 无重复、抽共享逻辑、无跨模块 refactor、最小 diff。

### Reviewer
- 函数级 correctness（Rust/TS/Python）、ownership/lifetime、
  precise file+function+patch suggestions。
- 架构级 review：检测 over-engineering / design drift。

## 数据写入不变量（本插件独有，必读）

- **不变量 1**：任何 `_mark_dirty_and_schedule(layer)` 之后，
  必然有一个 `_delayed_save` 读取到 `dirty=True` 并保存。
  机制：`_schedule_save` await 旧 task 终止后再建新 task，
  `_delayed_save` 执行前重新读取 dirty 标志。

- **不变量 2**：`_schedule_save` 必须 `await` 旧 task 真正终止，
  不可「cancel 后就忘」——否则旧 task 的半完成 save
  会把 dirty 标志错误清零，丢失新 mark_dirty 的数据。

- **不变量 3**：`DataManager.__init__` 中迁移旧格式
  （`_handle_old_format`）须在 `load_*` 与 dirty 清零**之后**，
  否则迁移写入的 universal 会被空文件加载覆盖，
  或 dirty 标志被 `__init__` 末尾的清零抹掉。

## 三层表征语义

- **universal（通用）**：全量注入每次回复，LLM 每轮重写，
  上限 `MAX_UNIVERSAL_PER_SESSION=10`。proficiency/confirmed_rounds
  为学习统计，注入时仅取 content。

- **contextual（情境）**：scene→behavior 全量注入，
  FIFO 容量管理 + 最新 20% 标记为缓冲位。
  `enable_contextual_merge` 配置控制是否按 difflib 相似度合并到通用/特定。

- **specific（特定）**：群内梗+释义，**仅注入 `trigger_regex` 命中
  用户消息的条目**（按需注入，prompt 不膨胀）。
  trigger_count/last_seen 在命中时累加。
  ReDoS 防护：正则长度 ≤200、拒绝嵌套量词、超长消息(>10000)不匹配。

## WebUI 边界

- 归一化在 `web_ui.normalize_webui_entries`，
  写入在 `DataManager.replace_layer`——职责分离。
- 先整体校验，任一条目非法抛 ValueError 不做部分写入；
  未变化条目保留 proficiency/trigger_count 等元数据。
- 前端 `esc()` 转义 `&<>"'`，portrait/Top 梗榜用 `textContent`。
- 路由以插件名前缀开头，经 `window.AstrBotPluginPage` 桥接。

## 测试

- 后端：`pytest tests/ -v`（25 项，覆盖边界/race/迁移/ReDoS/JSON 提取）。
- 前端：jsdom 冒烟测试基线（`tests/webui/`，需 Node 环境）。
- 任何改动 DataManager 保存逻辑的 PR，必须跑
  `test_schedule_save_no_data_loss_under_race` 回归。

## 语言规则

- 内部推理：ALWAYS English。
- 最终响应语言：MUST follow the user's question language。

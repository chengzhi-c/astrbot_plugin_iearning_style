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

- **不变量 1**：任何标记脏层之后，
  必然有对应的延迟保存读取到 dirty=True 并保存。

- **不变量 2**：调度保存时必须等待旧任务真正终止，
  不可「cancel 后就忘」——否则旧任务的半完成保存
  会把 dirty 标志错误清零，丢失新标记的数据。

- **不变量 3**：`DataManager.__init__` 中迁移旧格式
  须在 load 与 dirty 清零**之后**，
  否则迁移写入的 universal 会被空文件加载覆盖，
  或 dirty 标志被末尾清零抹掉。

## 三层表征语义（功能性）

- **universal（通用）**：稳定的说话基调（语气/用词/氛围），
  全量注入每次回复，LLM 每轮重写，上限 10 条。

- **contextual（情境）**：某场景出现时的固定反应
  （场景 → 行为），全量注入，按 FIFO 容量管理，
  最新 20% 标记为缓冲位；
  可配置是否按相似度合并到通用/特定。

- **specific（特定）**：群内梗+释义，
  **仅注入 trigger_regex 命中用户消息的条目**
  （按需注入，prompt 不膨胀）；
  trigger_count/last_seen 在命中时累加；
  ReDoS 防护：正则长度 ≤200、拒绝嵌套量词、超长消息(>10000)不匹配。

## WebUI 功能性约束

- 三层表征可通过面板内嵌页面查看与编辑，
  保存时整层替换、先校验后写入，未变化条目保留学习统计。
- 顶部/会话头支持「立即学习」「清空本会话」「导出 JSON」
  （等价于聊天命令）。
- 破坏性操作走确认弹窗；未保存修改时顶部横幅提示。
- 明/暗双主题、移动端抽屉式侧栏、
  快捷键（`/` 搜索 · `Ctrl/⌘+S` 保存当前层 · `Esc` 关闭）。
- 用户内容经 HTML 转义后渲染，portrait/Top 梗榜用 textContent。
- 路由以插件名前缀开头，经面板桥接调用。

## 测试

- 后端：`pytest tests/ -v`（25 项，覆盖边界/race/迁移/ReDoS/JSON 提取）。
- 任何改动 DataManager 保存逻辑的 PR，必须跑
  `test_schedule_save_no_data_loss_under_race` 回归。

## 语言规则

- 内部推理：ALWAYS English。
- 最终响应语言：MUST follow the user's question language。

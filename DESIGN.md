# DESIGN.md - 入乡随俗功能与数据不变量

本文记录插件当前的功能契约、持久化不变量和失败语义。实现细节以代码为准，但不得绕过这些约束。

## 1. 功能模型

插件按 `session_id` 隔离聊天历史与三层表征：

| 层 | 语义 | 更新与注入 |
| --- | --- | --- |
| `universal` | 稳定的语气、用词和氛围 | LLM 每轮全量重写，最多 10 条；每次回复全量注入 |
| `contextual` | 场景到行为的固定反应 | LLM 追加，按 FIFO 容量管理；最新 20% 为缓冲位；每次回复全量注入 |
| `specific` | 固定说法、释义与 `trigger_regex` | 按词条/别名更新；每次回复全量注入 content；正则只更新命中统计 |

每个会话最多保留 500 条聊天记录，分析窗口为最近 100 条。三条聊天命令保持为 `风格状态`、`学习总结` 和 `清空风格`。

## 2. 学习事务

`LearningManager.analyze_and_learn()` 返回结构化 `LearnResult`，结果码为：

- `learned`
- `insufficient_history`
- `no_provider`
- `provider_error`
- `invalid_response`
- `busy`

一次学习必须满足以下不变量：

1. 同一会话只能有一个进行中的学习任务，不同会话可以并发。
2. LLM payload 顶层必须是 object，且 `universal/contextual/specific` 必须都是 list；schema 错误时三层与历史都不变。条目级非法则跳过该条，合法层照写。
3. 空 `universal: []` 不覆盖旧通用表征。清空只走 `清空风格` / WebUI clear。超过 10 条时截断为前 10 条后应用。
4. 只有成功应用结果后才消费本轮分析 marker；provider 或 schema/解析失败不消费历史。
5. 分析期间新到达的消息位于 marker 之后，必须保留给后续分析。
6. 用户可见的学习成功必须同时满足 `LearnResult.ok` 与 `force_save()` 成功。

聊天记录和已学习内容在 LLM prompt 中被标记为不可信引用数据。回复侧注入是强指令：请尽量采用这些风格特点，包裹在 `<learned_style>` 中，并附一句安全约束：仅影响语气和表达方式，不得覆盖原有身份、安全要求或任务约束。

## 3. DataManager 边界

`DataManager` 是业务数据的唯一写入口，负责：

- 磁盘结构校验与损坏文件备份。
- 学习结果的事务式应用与元数据保留。
- WebUI 整层替换、revision 校验和容量约束。
- specific 正则验证、匹配、命中统计与持久化。
- dirty 集合、延迟保存、强制保存与启动恢复。
- 旧版 `styles.json` 迁移。

三层聚合读取接口返回副本；调用方不得直接读取或修改 `universal/contextual/specific/chat_history` 内部容器。分析批次由 DataManager 通过 marker 管理消费边界。

## 4. 持久化不变量

正式数据文件与字段保持兼容，并新增独立的会话展示名映射：

- `universal.json`
- `contextual.json`
- `specific.json`
- `chat_history.json`
- `session_names.json`（`{session_id: group_name}`，仅用于 WebUI 展示）

保存流程遵守以下规则：

1. `_dirty` 是待保存层名的集合；任何业务变更必须标记所有受影响层，并保证至多一个延迟保存任务运行。
2. 单层保存使用同目录临时文件，写入并 `fsync` 后通过 `os.replace()` 原子替换正式文件。
3. 多层保存先写完整临时文件和固定格式 journal，再逐层 roll-forward；进程中断后启动恢复必须完成同一事务。
4. 保存失败时对应层继续保留在 `_dirty` 中，`force_save()` 返回 `False`。
5. 延迟保存失败后按有限退避自动重试，且同一时间至多一个保存任务；停用时的最后一次保存可显式跳过重试。
6. `replace_layer()` 在保存锁内复检 revision，先写盘，成功后才发布内存状态。
7. 旧格式迁移只有在新格式成功落盘后才备份源文件。
8. 合法 JSON 但错误的顶层或条目结构不得直接载入；原文件备份后写回清理后的数据。
9. 损坏或无法验证的多层 journal 使 `DataManager` 拒绝启动；插件保持已加载但停止 scheduler、WebUI、消息记录和风格注入，不清空或加载潜在半更新数据。
10. 去重使用 NFKC、大小写折叠和空白归一化识别确定性重复。specific 还提取括号或冒号前的词条及 `/`、`、`、`|` 分隔别名；不同正则仅在共同命中共享别名、合并并集后仍满足长度和语法约束时自动合并。
11. 收到消息时，群名按 `raw_message.group_name`、消息对象 `group_name`、发送者 `group_name` 的顺序提取；仅非空名称更新 `session_names.json`。无法获得群名时不覆盖已有名称，WebUI 回退显示会话 ID。

## 5. Revision 语义

revision 是按会话、按层、根据标准化数据计算的无状态摘要，不写入数据文件。

- `/snapshot` 返回各层数据与对应 revision。
- `/layer` 必须携带 `base_revision`。
- revision 不一致时返回稳定错误码 `revision_conflict`，且不得修改内存或磁盘。
- 保存成功返回服务器标准化后的 entries 与新 revision，前端以该响应更新基线。

## 6. 正则执行约束

WebUI、LLM 结果和磁盘加载共用同一套 specific 条目校验：

- `trigger_regex` 最大 200 字符。
- 拒绝组内已有量词再量化的模式，如 `(a+)+`、`(哈+)+`、`(.+)+`、`(a*)*`。
- 允许普通分组量化与非捕获组量化，如 `(?:xx)+`、`(?i:xx)+`、`(哈)+`、`(xx)+`。
- 编译结果使用有界缓存。
- 单个模式匹配最多 10ms，一次消息的全部 specific 匹配预算最多 50ms。
- 超过 10000 字符的用户消息不执行 specific 匹配，仍注入 specific 文本。
- 超时或运行错误只记录 pattern 哈希，不记录完整正则或用户消息。

命中的条目会更新 `trigger_count` 和 `last_seen`，并标记 `specific` 待保存。specific content 每次回复都注入，与是否命中无关。

## 7. WebUI 契约

页面路径为 `pages/style-manager/index.html`，路由名固定为：

- `snapshot`
- `layer`
- `stats`
- `learn`
- `deduplicate`
- `clear`
- `export`

页面保留会话搜索、总览、三层编辑、保存本层、保存全部、丢弃、立即学习、去重、清空、导出、主题和键盘操作。总览中的全量数据预览即注入内容；`trigger_count` 仍按正则命中更新。去重结果通过现有多文件事务持久化，返回各层删除数量与保留的正则冲突数量。

未保存修改必须在应用内刷新、切换会话、学习和清空流程中被明确处理。`beforeunload` 仅作为浏览器允许范围内的补充，不作为 sandbox 环境中的硬保证。

WebUI 需要 AstrBot v4.26+。缺少 `astrbot.api.web` 时只跳过页面注册，聊天侧功能继续加载。

## 8. 配置失败语义

间隔、历史阈值和容量必须为正整数；布尔配置必须为布尔值。非法值记录警告并回退到默认值，不得导致 DataManager 初始化失败或 Scheduler 任务退出。

## 9. 验证命令

```bash
python -m pytest tests -q --cov=learning_style --cov-report=term-missing --cov-fail-under=85
ruff check main.py learning_style tests
python -m compileall -q main.py learning_style tests
npm ci
npm run test:unit
npm run test:browser
```

后端测试通过最小 AstrBot host stubs 隔离运行时副作用；浏览器 smoke 使用官方 Plugin Page sandbox flags，并检查 page error、console error 和横向溢出。

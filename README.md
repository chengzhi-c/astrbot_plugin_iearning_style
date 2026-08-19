# astrbot_plugin_iearning_style（入乡随俗）

让机器人从聊天中学习并模仿当前会话的表达方式。插件按会话保存聊天历史，调用 LLM 提取三层风格表征，并在后续回复中按规则注入。

## 运行要求

- 插件核心功能支持不含 Plugin Pages 的旧版 AstrBot。
- 面板内风格管理页面需要 AstrBot v4.26 或更高版本；旧版本会跳过页面注册，不影响聊天记录、自动学习、命令和风格注入。
- 运行时依赖见 `requirements.txt`，AstrBot 安装插件时会一并安装。

## 功能

| 层级 | 含义 | 注入方式 |
|---|---|---|
| 通用表征 | 稳定的语气、用词和表达习惯 | 每次回复全量注入，最多 10 条 |
| 情境表征 | 特定场景下的行为模式 | 每次回复全量注入，按 FIFO 容量管理 |
| 特定表征 | 群内梗、固定说法及其触发正则 | 仅当 `trigger_regex` 命中当前用户消息时注入 |

- 自动记录每个会话最近 500 条非机器人消息，单次分析使用最近 100 条。
- 每轮学习只调用一次 LLM；结果会先整体校验，再一次性更新三层数据。
- 无效响应、provider 失败或磁盘保存失败不会被报告为学习成功。
- 分析期间新到达的消息不会因本轮学习完成而被清除。
- 特定表征命中后会更新 `trigger_count` 与 `last_seen` 并持久化。
- 特定正则限制长度、拒绝明显的嵌套量词，并执行单模式 10ms、整次 50ms 的运行时匹配预算。

## 聊天命令

- `风格状态`：查看当前会话三层表征数量和 Top-3。
- `学习总结`：立即分析当前会话。
- `清空风格`：清空当前会话三层表征，不清除聊天历史。

## 风格管理页面

在 AstrBot 面板中打开：**扩展 → 插件详情 → 打开插件页面**。

- 会话列表、搜索与全局统计。群聊收到新消息后，列表会优先显示平台事件提供的群名称；未提供名称时保留会话 ID 作为回退。
- 通用、情境、特定三层编辑，支持保存本层、保存全部和丢弃修改。
- 全量风格数据预览与 Top 梗榜。特定层预览展示服务器保存的全部条目，不代表某条当前消息实际触发的注入结果。
- 立即学习、去重本会话、清空本会话和导出 JSON。去重会识别全半角、大小写、空白，以及括号前词条和 `/` 分隔别名；同词条的不同正则仅在共同命中别名且合并后仍通过校验时合并，否则保留。
- 明暗主题、移动端侧栏、键盘导航，以及 `/`、`Ctrl/Command+S`、`Esc` 快捷键。

页面保存使用 revision 检测并发更新。若后台学习已更新同一层，旧页面不会静默覆盖新数据，而会提示冲突并刷新服务器版本。保存成功只在数据已经原子写入磁盘后返回；写盘失败时服务器内存不会提前发布该次整层替换。

## 数据可靠性

- 数据文件保持为 `universal.json`、`contextual.json`、`specific.json`、`chat_history.json` 和 `session_names.json`。后者仅保存会话 ID 到最近群名的映射。
- 单文件保存使用同目录临时文件、`fsync` 和原子替换。
- 多层同时保存使用可恢复的 roll-forward journal，避免进程中断后留下跨文件半更新。
- 启动时会恢复有效的临时保存；结构损坏的单层文件会备份后按空数据恢复。无法证明完整性的多层保存 journal 会使插件停止读写并保留原始文件，避免静默覆盖跨层半更新数据；修复事务后重启即可恢复。
- 写盘失败会保留待保存状态并按有限退避自动重试；插件停用时只做一次最后保存尝试，不会留下后台重试任务。
- 旧版 `styles.json` 在新格式成功落盘后才会备份为迁移文件。

## 配置

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `llm_provider_id` | 空 | 学习分析使用的 provider；留空使用系统默认 provider |
| `analysis_interval_seconds` | 3600 | 自动分析间隔，必须为正整数 |
| `maintenance_interval_seconds` | 86400 | 维护任务间隔，必须为正整数 |
| `min_history_for_analysis` | 10 | 触发分析的最少消息数，必须为正整数 |
| `max_specific_per_session` | 200 | 每个会话的特定表征容量，必须为正整数 |
| `max_contextual_per_session` | 150 | 每个会话的情境表征容量，必须为正整数 |
| `enable_style_injection` | true | 是否注入已学习风格 |
| `enable_contextual_merge` | true | 是否在维护时合并情境缓冲表征 |
| `webui_enabled` | true | 是否注册风格管理页面 |

非法类型或非正整数会在运行时回退到默认值，不会让调度任务退出。

## 开发验证

```bash
python -m pip install -r requirements.txt pytest pytest-cov ruff
python -m pytest tests -q --cov=learning_style --cov-report=term-missing --cov-fail-under=85
ruff check main.py learning_style tests
python -m compileall -q main.py learning_style tests
npm ci
npm run test:unit
npx playwright install chromium
npm run test:browser
```

浏览器测试使用 AstrBot Plugin Page 的官方 iframe sandbox flags，覆盖启动、保存全部、破坏性操作取消、主题、键盘与窄屏布局。

## QQ 群

作者不经常查看 issue，可通过 QQ 群提醒：1098607348。

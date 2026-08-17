# AGENTS.md - 入乡随俗维护约定

## 修改原则

- 优先修根因，先搜索所有调用方，再修改共享边界。
- 保持最小可靠实现；不引入数据库、前端框架、状态库、构建器或单实现抽象层。
- 不改变现有 JSON 文件名、字段名、三条聊天命令和既有 Web 路由；新增路由必须同步更新契约测试。
- 不直接修改 `DataManager` 的内部数据容器；读写都走其公共接口。
- 新行为或缺陷修复必须先有能在旧实现上按预期失败的测试。

## 数据不变量

- `_dirty` 保存所有待落盘层；变更多个层时必须一次标记完整。
- 延迟保存任务至多一个；保存期间出现的新 dirty 必须留给下一轮。
- 单层写入使用临时文件、`fsync`、`os.replace()`。
- 多层写入使用 roll-forward journal；启动时先恢复事务和有效临时文件，再加载正式数据。
- 保存失败保留 dirty，`force_save()` 返回 `False`。
- WebUI `replace_layer()` 在保存锁内复检 revision，写盘成功后才发布内存。
- 学习结果先整体校验再一次性应用；失败不消费历史 marker。
- 旧格式迁移必须先成功写入新文件，再备份 `styles.json`。

## 三层语义

- `universal`：每轮全量重写，最多 10 条，每次回复全量注入。
- `contextual`：追加并按 FIFO 管理，最新 20% 为缓冲位，每次回复全量注入。
- `specific`：仅正则命中当前用户消息时注入；命中后更新 `trigger_count/last_seen`。
- specific 校验必须共用 DataManager 入口。运行时限制为单模式 10ms、总预算 50ms、消息最大 10000 字符。

## WebUI 约束

- `app.js` 负责流程编排；view 模块只渲染并回传用户意图。
- 保存本层和保存全部必须携带 revision；冲突不得覆盖服务器数据。
- 破坏性操作使用原生 dialog；取消按钮获得初始焦点，Enter 不得确认清空。
- 用户内容只通过文本节点或转义后的受控模板渲染。
- 主题来自 AstrBot bridge context；手动切换仅在当前页面生命周期内覆盖。
- 浏览器回归必须使用 `sandbox="allow-scripts allow-forms allow-downloads"`。

## 验证

```bash
python -m pytest tests -q --cov=learning_style --cov-report=term-missing --cov-fail-under=85
ruff check main.py learning_style tests
python -m compileall -q main.py learning_style tests
npm ci
npm run test:unit
npx playwright install chromium
npm run test:browser
```

同时对 `pages/style-manager/src` 和 `tests/frontend` 中所有 JavaScript 文件执行 `node --check`，并运行 Python 3.10 AST 解析及 `git diff --check`。

## 发版

- `metadata.yaml`、`main.py` 的 `@register` 与 `pages/style-manager/index.html` 的 `verTag` 必须保持同一版本。
- 只提交源码、测试、依赖锁文件、CI 和用户/开发文档。
- 不提交运行时数据、缓存、截图、临时报告、本机路径或凭据。

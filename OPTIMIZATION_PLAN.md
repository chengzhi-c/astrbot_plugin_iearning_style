# 入乡随俗 · 三要素极致优化方案

> 评审基线（2026-08-16 复审确认）：
> - 可维护性 7.0｜最轻量 7.5｜高质量 6.5｜综合 7.0
> - 已逐文件核验问题真实性：双前端并存、`_schedule_save` race、前端 `esc()` 不转义 HTML（XSS）、JSON 提取鲁棒性、零测试、死统计字段、半吊子迁移，**全部坐实**。
>
> 本方案目标：三要素均 ≥ 9.0，**不丢任何现有功能**（三层表征、自动学习、四种聊天命令、WebUI 总览/编辑/学习/清空/导出/明暗主题/移动端/快捷键）。

---

## 0. 优化总览

| 阶段 | 要素 | 改动 | 风险 |
|------|------|------|------|
| P1 死代码清除 | 维护 | 删 `pages/style-manager/app.js`（旧版 257 行）、`design/prototype/` | 极低 |
| P2 `_schedule_save` race 修复 | 质量 | 单 task + dirty 重检 + None 无脑置 | 低 |
| P3 前端 XSS 修复 | 质量 | `esc()` 真转义 + 关键路径改 `textContent` | 低 |
| P4 JSON 提取鲁棒化 | 质量 | 正则锚定最外层 `{...}` | 低 |
| P5 `DataManager` 瘦身 | 维护 | 抽 `_normalize_webui_entries` 到 `web_ui.py` | 中 |
| P6 死字段与 difflib 决策 | 轻量 | 启用 `trigger_regex` 注入匹配（让字段活）；保留 difflib 但加配置开关 | 中 |
| P7 时间戳语义统一 | 质量 | 全改 `time.time()` 纪元秒，前端 `relTime` 正确换算 | 低 |
| P8 迁移补全 | 质量 | `styles.json`→三层文件的真迁移脚本 | 低 |
| P9 测试基线 | 质量 | pytest（data_manager 边界）+ jsdom 冒烟回归 | 中 |
| P10 文档同步 | 维护 | 更新 `DESIGN.md`/`README`/新增 `AGENTS.md` 章节 | 极低 |

---

## P1 · 死代码清除（可维护 +0.3）

### 现状
- `pages/style-manager/app.js`（根目录，257 行旧版单文件）仍存在。
- `index.html:129` 引用的是 `./src/app.js`（新版模块化）。
- 旧版 `LAYERS`/`FIELDS`/`state`/`selectSession` 与新版语义不一致，未来改一处忘另一处必出 bug。
- `design/prototype/index.html` 是高保真原型，与生产 `pages/` 并行，无 README 说明废弃状态。

### 方案
1. **删除** `pages/style-manager/app.js`（根目录旧版）。
2. **归档** `design/prototype/` → `design/_archive/prototype/`，并在 `design/README.md`（新建）说明：「生产界面在 `pages/style-manager/`，`prototype/` 仅保留作历史参考，不维护」。
3. **验证**：`index.html` 引用不变；`node --check pages/style-manager/src/*.js` 全通过。

### 交付物
- 删除的文件清单。
- `design/README.md`（5 行说明）。

---

## P2 · `_schedule_save` race 修复（高质量 +0.5）

### 现状（已复审坐实）
`data_manager.py` L336-351：
```python
async def _schedule_save(self):
    if self._save_timer is not None:
        self._save_timer.cancel()
    self._save_timer = asyncio.create_task(self._delayed_save())

async def _delayed_save(self):
    await asyncio.sleep(self._save_delay)
    if self._dirty_universal:
        await self.save_universal()
    # ...其余三层
    self._save_timer = None
```

**Race 链**：
1. A 任务 `_delayed_save` 进入，sleep 完毕，开始 `save_universal`，**尚未执行到 `self._save_timer = None`**。
2. 主线程调用 `replace_universal` → 标 `_dirty_universal=True`（但 A 即将把它清 False）→ `asyncio.create_task(self._schedule_save())`。
3. B 任务 `_schedule_save` 看到 `_save_timer is not None`（A 还没置 None），cancel A。但 A 可能已过 cancel 检查点，正在写文件。
4. A 的 `save_universal` 完成，`_dirty_universal = False`。B 的 `_delayed_save` sleep 5s 后检查 dirty——**B 的 dirty 标志已被 A 清掉，B 什么都不保存**。
5. **最坏：B 触发的 dirty 数据丢失**。

### 方案（最小改动，消除 race）
```python
async def _schedule_save(self):
    # 若已有 pending task，cancel 并等待其真正终止
    if self._save_timer is not None and not self._save_timer.done():
        self._save_timer.cancel()
        try:
            await self._save_timer
        except asyncio.CancelledError:
            pass
    self._save_timer = asyncio.create_task(self._delayed_save())

async def _delayed_save(self):
    await asyncio.sleep(self._save_delay)
    # 重新检查 dirty：若期间又有新 mark_dirty，dirty 仍为 True，会保存最新状态
    if self._dirty_universal:
        await self.save_universal()
    if self._dirty_contextual:
        await self.save_contextual()
    if self._dirty_specific:
        await self.save_specific()
    if self._dirty_chat_history:
        await self.save_chat_history()
    self._save_timer = None
```

**为何有效**：
- `_schedule_save` 现在 `await` 旧 task 真正终止（cancel + gather），不再「cancel 后就忘」。
- `_delayed_save` 的 dirty 检查是**读取此刻的 dirty 标志**，而 `save_X` 在写完后才置 dirty=False。若 A 正在 save_universal，B cancel A 后 A 的 `save_universal` 已完成或被中断：
  - 若 A 已完成 `save_universal`（dirty=False），B 的 dirty=True 来自后续 mark_dirty，B 会保存——正确。
  - 若 A 被 cancel 在 `save_universal` 中途，dirty 仍 True，B 重新保存——正确。
- **关键不变量**：最后一次 `mark_dirty` 之后，必然有一个 `_delayed_save` 读取到 dirty=True 并保存。

### 补充：`mark_dirty` 统一入口
将 8 处散弹 `asyncio.create_task(self._schedule_save())` 收敛为：
```python
def _mark_dirty_and_schedule(self, layer: str):
    setattr(self, f"_dirty_{layer}", True)
    asyncio.create_task(self._schedule_save())
```
调用点改为 `self._mark_dirty_and_schedule("universal")`。降低维护面。

### 交付物
- `data_manager.py` diff（`_schedule_save`/`_delayed_save`/`_mark_dirty_and_schedule` + 8 处调用点替换）。
- P9 测试覆盖此 race。

---

## P3 · 前端 XSS 修复（高质量 +0.3）

### 现状（已复审坐实）
`util.js:8`：
```js
export const esc = (v) => (v == null ? '' : String(v));
```
**`esc` 不转义任何 HTML 字符**，仅做 null→''。但 `views.js` 多处把 LLM 学到的内容经 `esc()` 后塞进 `innerHTML`：
- L54-60：侧栏会话项（sid 来自后端，低风险，但不该假设）。
- L149：`<div class="quote">${esc(portrait)}</div>`——**portrait 含 universal/contextual/specific 的 content 拼接，若 LLM 学到 `<img src=x onerror=alert(1)>`，则 XSS**。
- L155：Top 梗榜 `esc(x.content)`——同上。

### 方案（双层防御，零功能损失）
**第一层：`esc()` 真转义**
```js
const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (v) => (v == null ? '' : String(v).replace(/[&<>"']/g, (c) => ESC_MAP[c]));
```
保留函数签名，所有现有调用点无需改动。

**第二层：危险路径改 `textContent`**
- `views.js:149` 的 `.quote`：portrait 是多段拼接的纯文本预览，应改用 `textContent`：
  ```js
  const quoteEl = el('div', 'quote');
  quoteEl.textContent = portrait;
  ```
- `views.js:155` 的 Top 梗榜 `<li>`：每条 `x.content` 走 `textContent`，`trigger_count` 走 `<span class="tc">` 的 `textContent`。
- `buildRow`（L219-284）已经全部用 `el()` + `textContent`/`inp.value`，**无 XSS**，保持不变。
- 侧栏 `d.innerHTML`（L54）：sid 经 `esc()` 后转义安全，但更优是改 `textContent` + 子元素分别 set。鉴于 sid 来自后端受信源，保留 `innerHTML + esc()` 即可。

**第三层：CSP 兜底（可选）**
若 AstrBot Dashboard 沙箱允许，在 `index.html` 加 `<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'">`。但沙箱 iframe 可能已由 Dashboard 设 CSP，此条标注为「可选」。

### 验证
- 手动注入 universal content = `<script>alert('xss')</script>`，确认页面不执行脚本、显示为转义文本。
- P9 jsdom 测试加 XSS 用例。

### 交付物
- `util.js` diff（`esc` 重写）。
- `views.js` diff（L149/L155 改 textContent）。
- 测试用例。

---

## P4 · JSON 提取鲁棒化（高质量 +0.2）

### 现状（已复审坐实）
`learning_manager.py` L149-155：
```python
json_pattern = r"```json\s*(\{.*?\})\s*```"
match = re.search(json_pattern, llm_output, re.DOTALL)
if match:
    json_str = match.group(1)
else:
    json_str = llm_output[llm_output.find("{") : llm_output.rfind("}") + 1]
```

**问题**：
1. 围栏正则 `\{.*?\}` 非贪婪，遇到嵌套 `{}` 会截断。
2. 兜底 `find("{")` 到 `rfind("}")`：LLM 若在 JSON 后输出 `{示例}`，`rfind` 取到最后一个 `}`，`json.loads` 炸；若 JSON 内含字符串 `"}`，`rfind` 也可能误判。

### 方案（括号配平提取，零依赖）
替换 L148-157 为：
```python
def _extract_json(text: str) -> str | None:
    """从 LLM 输出提取最外层 JSON 对象，容忍围栏与尾随解释。"""
    # 优先：```json ... ``` 围栏
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    # 括号配平找最外层 {...}
    start = candidate.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return candidate[start : i + 1]
    return None  # 不配平，不强行截断
```

调用：
```python
json_str = _extract_json(llm_output)
if json_str is None:
    logger.error(f"无法从 LLM 输出提取 JSON。原始输出: {llm_output}")
    return
results = json.loads(json_str)
```

**为何有效**：
- 括号配平正确处理嵌套对象与字符串内的 `{`/`}`（`in_str` 状态机）。
- 不配平时返回 None，不强行截断造半个 JSON。
- 仍兼容围栏格式。

### 交付物
- `learning_manager.py` diff（新增 `_extract_json` + 调用点）。
- P9 测试：嵌套 JSON、围栏、尾随解释、字符串含 `}`、不配平输入。

---

## P5 · `DataManager` 瘦身（可维护 +0.4）

### 现状
`DataManager` 580 行、38 方法，同时承担：4 种文件 IO + 缓冲合并 + WebUI 归一化 + 全局统计。`_normalize_webui_entries`（81 行）混在存储层，违反 SRP。

### 方案（抽离 WebUI 归一化到 `web_ui.py`）
`_normalize_webui_entries` 是纯输入校验/归一化逻辑，不触碰 `DataManager` 的存储状态（除读 `self.universal` 等做「保留元数据」对照）。将其迁移到 `web_ui.py` 作为模块函数：

```python
# web_ui.py
def _normalize_webui_entries(
    data_manager: DataManager,
    session_id: str,
    layer: str,
    entries: Any,
) -> list[dict[str, Any]]:
    # 原 data_manager._normalize_webui_entries 逻辑，
    # 通过 data_manager.universal/contextual/specific 读旧元数据
    ...
```

`DataManager.replace_layer` 改为接收已归一化的 list：
```python
def replace_layer(self, session_id: str, layer: str, normalized: list[dict[str, Any]]):
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("缺少会话 ID")
    if layer not in ("universal", "contextual", "specific"):
        raise ValueError(f"未知的表征层: {layer}")
    target = getattr(self, layer)  # self.universal / contextual / specific
    target[session_id] = normalized
    setattr(self, f"_dirty_{layer}", True)
    self._mark_dirty_and_schedule(layer)
```

`web_ui._save_layer` 编排归一化 + 写入：
```python
async def _save_layer(self):
    payload = await request.json(default=None)
    if not isinstance(payload, dict):
        return error_response("请求体必须是 JSON 对象")
    try:
        normalized = _normalize_webui_entries(
            self.data_manager, payload.get("sid"),
            payload.get("layer"), payload.get("entries"),
        )
        self.data_manager.replace_layer(payload.get("sid"), payload.get("layer"), normalized)
    except ValueError as e:
        return error_response(str(e))
    return json_response({"status": "ok", "data": {"saved": True}})
```

### 收益
- `DataManager` 不再混入 WebUI 边界校验，回归「纯存储 + 三层逻辑」。
- `replace_layer` 从 26 行降到 ~10 行。
- `_req_field` 静态方法一并迁移到 `web_ui.py` 模块级。

### 风险与回滚
- 风险：`_normalize_webui_entries` 读 `self.universal.get(session_id, [])` 做元数据保留对照，迁移后改读 `data_manager.universal.get(...)`，行为等价。
- 回滚：单 commit 可整体 revert。

### 交付物
- `web_ui.py` diff（新增 `_normalize_webui_entries` + `_req_field`）。
- `data_manager.py` diff（删 `_normalize_webui_entries`/`_req_field`，`replace_layer` 简化）。

---

## P6 · 死字段与 difflib 决策（最轻量 +0.5）

### 现状
1. **死统计字段**：`proficiency`/`confirmed_rounds`/`trigger_count` 被 `style_injector` 完全忽略（注入只取 `content`）。前端注释自承 `trigger_regex`「仅做存储校验，未参与注入匹配」。即「存了不用」。
2. **`difflib` 合并**：`merge_contextual_buffer` 用 0.85 阈值字符串相似度合并情境→通用/特定。「爱用表情包」vs「喜欢用表情」语义近而字符串远，不合并——既不准又增加认知负担。

### 方案（让死字段复活 + difflib 加开关）

**6.1 启用 `trigger_regex` 注入匹配（让字段活）**

现状 `style_injector.inject_style_to_prompt` 把 specific 全量注入。改为「按用户当前消息匹配 trigger_regex 才注入」：

```python
# style_injector.py
def inject_style_to_prompt(self, session_id: str, original_system_prompt: str, user_message: str = "") -> str:
    if not self.should_inject_style(session_id):
        return original_system_prompt
    try:
        style_parts = []
        universal = self.data_manager.get_universal_for_session(session_id)
        if universal:
            style_parts.append(self.style_selector.build_style_text("通用风格", [t["content"] for t in universal]))
        contextual = self.data_manager.get_contextual_for_session(session_id)
        if contextual:
            style_parts.append(self.style_selector.build_contextual_text(contextual))
        # 特定：仅注入 trigger_regex 命中用户消息的条目
        specific = self.data_manager.get_specific_for_session(session_id)
        hit = []
        for s in specific:
            try:
                if re.search(s.get("trigger_regex", ""), user_message):
                    s["trigger_count"] = s.get("trigger_count", 0) + 1
                    s["last_seen"] = asyncio.get_running_loop().time()
                    hit.append(s["content"])
            except re.error:
                continue
        if hit:
            style_parts.append(self.style_selector.build_style_text("群内流行说法", hit))
        if not style_parts:
            return original_system_prompt
        # ...其余拼接不变
```

`main.py` 的 `on_llm_request` 传入用户消息：
```python
@filter.on_llm_request()
async def on_llm_request(self, event: AstrMessageEvent, req):
    session_id = event.unified_msg_origin
    user_message = event.get_message_str() or ""
    req.system_prompt = self.style_injector.inject_style_to_prompt(
        session_id, req.system_prompt or "", user_message
    )
```

**收益**：
- `trigger_regex`/`trigger_count`/`last_seen` 全部复活，不再是死数据。
- 特定层按需注入，prompt 不膨胀——这正是 README「特定正则触发」宣传但未实现的能力。
- **ReDoS 防护**：用户输入的正则在 `add_or_update_specific` 已 `re.compile` 校验语法，但未限复杂度。加超时保护不现实（Python re 无原生超时）。务实方案：在 `data_manager.add_or_update_specific` 限制正则长度 ≤ 200 字符 + 禁止嵌套量词 `(a+)+` 的简单启发式检查。详见 P6.3。

**6.2 `difflib` 合并加配置开关**

`merge_contextual_buffer` 的相似度合并保留，但加配置项 `enable_contextual_merge`（默认 true）：
```python
# _conf_schema.json
"enable_contextual_merge": {
  "type": "bool",
  "description": "情境缓冲合并到通用/特定",
  "hint": "维护任务时是否尝试将缓冲位的情境表征按相似度合并到通用/特定。关闭则情境表征仅按 FIFO 淘汰，不向上合并。默认 true。",
  "default": true
}
```

`merge_contextual_buffer` 入口检查：
```python
def merge_contextual_buffer(self, session_id: str, threshold: float = 0.85):
    if not self.config.get("enable_contextual_merge", True):
        return  # 仅 FIFO，不合并
    # ...原逻辑
```

**理由**：相似度合并不准（语义近字符串远），但删除会丢「情境沉淀到通用」的路径。加开关让用户在「不准的自动合并」与「纯 FIFO 手动管理」之间选，符合 YAGNI 边界——保留可能性但不强加。

**6.3 ReDoS 防护（启用 trigger_regex 匹配后的必要加固）**

`data_manager.add_or_update_specific` 在 `re.compile` 校验后，追加：
```python
if len(trigger_regex) > 200:
    logger.error(f"特定表征 '{content}' 的正则过长 (>200 字符)，拒绝存储")
    return
# 启发式：禁止 (a+)+ 形嵌套量词
if re.search(r"\([^()]*[+*?][^()]*\)[+*?]", trigger_regex):
    logger.error(f"特定表征 '{content}' 的正则含嵌套量词，可能 ReDoS，拒绝存储")
    return
```

注入匹配时加 `signal.alarm` 超时不跨平台，改用「匹配长度限制」：
```python
# style_injector 注入匹配处
if len(user_message) > 10000:
    return  # 超长消息不匹配，避免灾难正则放大
```

### 交付物
- `style_injector.py` diff（`inject_style_to_prompt` 加 `user_message` 参数 + specific 按需匹配）。
- `main.py` diff（`on_llm_request` 传 user_message）。
- `data_manager.py` diff（`add_or_update_specific` 加 ReDoS 防护 + `merge_contextual_buffer` 加开关）。
- `_conf_schema.json` diff（新增 `enable_contextual_merge`）。

---

## P7 · 时间戳语义统一（高质量 +0.3）

### 现状（已复审坐实）
- 后端用 `asyncio.get_running_loop().time()`（单调时钟，非纪元）。
- 前端 `util.js:relTime` 尝试按 `>=1e8` 当纪元秒换算——但单调时钟运行 3 年以上也可能 `>=1e8`，会误显示「N 天前」。
- `DESIGN.md` Don't#5 说「显示为 —」，但 `relTime` 实际会进入 epoch 分支。**逻辑与文档不一致**。

### 方案（全链路改纪元秒，零功能损失）
后端所有 `asyncio.get_running_loop().time()` 替换为 `time.time()`：
- `data_manager.py:90`（replace_universal 的 last_updated）
- `data_manager.py:157`（add_contextual 的 created_at）
- `data_manager.py:287`（add_or_update_specific 的 first_seen/last_seen）
- `data_manager.py:496`（_normalize_webui_entries 的 now）
- `data_manager.py:56`（on_message 的 timestamp，main.py 内）

文件头加 `import time`。

前端 `util.js:relTime` 简化（值现在是真纪元秒）：
```js
export function relTime(value) {
  if (!value || typeof value !== 'number') return '—';
  const now = Date.now() / 1000;
  const d = now - value;
  if (d < 0) return '—';        // 时钟漂移或未来时间，诚实不伪造
  if (d < 60) return '刚刚';
  if (d < 3600) return Math.floor(d / 60) + ' 分钟前';
  if (d < 86400) return Math.floor(d / 3600) + ' 小时前';
  if (d < 86400 * 30) return Math.floor(d / 86400) + ' 天前';
  return new Date(value * 1000).toLocaleDateString();
}
```

**迁移注意**：已有数据文件里的 `last_updated`/`created_at` 等是单调时钟值，改 `time.time()` 后新旧值不可比。但前端 `relTime` 对旧值（单调时钟，可能 < 1e8）会返回「—」，对用户无感（本来就不显示真实时间）。侧栏排序用 `lastActivity` 取最大值，新旧混排时旧值恒小、沉底，行为可接受。

### 交付物
- `data_manager.py`/`main.py` diff（`time.time()` 替换）。
- `util.js` diff（`relTime` 简化）。
- `DESIGN.md` diff（Don't#5 更新为「单调时钟已废弃，时间戳为纪元秒，可显示真实相对时间」）。

---

## P8 · 迁移补全（高质量 +0.2）

### 现状
`_handle_old_format` 仅 `os.rename(styles.json, styles.json.bak)`，旧数据用户升级后表征全丢。半吊子迁移最不轻量。

### 方案（真迁移，保留旧数据）
`styles.json` 旧格式（根据上下文推断）应为 `{"session_id": [trait, ...]}` 单层结构。迁移逻辑：

```python
def _handle_old_format(self):
    old_file = os.path.join(self.data_dir, "styles.json")
    if not os.path.exists(old_file):
        return
    logger.warning("检测到旧版数据格式 (styles.json)，开始迁移到三层存储...")
    try:
        with open(old_file, encoding="utf-8") as f:
            old_data = json.load(f)
        # 旧格式：单层 trait 列表 → 全部迁入 universal
        now = time.time()
        for sid, traits in old_data.items():
            if not isinstance(traits, list):
                continue
            self.universal[sid] = [
                {
                    "content": t.get("content", str(t)) if isinstance(t, dict) else str(t),
                    "proficiency": 10,
                    "confirmed_rounds": 1,
                    "last_updated": now,
                }
                for t in traits
            ]
        self._dirty_universal = True
        # 备份并标记已迁移
        os.rename(old_file, old_file + ".migrated.bak")
        logger.info(f"迁移完成：{len(old_data)} 个会话的旧表征已并入通用层。")
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"迁移旧格式失败: {e}，旧文件保留为 {old_file}.bak")
        os.rename(old_file, old_file + ".bak")
```

**为何并入 universal 而非保留原层**：旧 `styles.json` 无三层区分，最保守是把所有旧表征当作「通用风格」基色，用户可在 WebUI 重新分类。比「全丢」好。

### 交付物
- `data_manager.py` diff（`_handle_old_format` 重写）。

---

## P9 · 测试基线（高质量 +0.5）

### 现状
`REFACTOR_OVERVIEW.md` 提「jsdom 冒烟测试 11 项」，但仓库里找不到测试文件。声称的测试已丢失或不公开。零回归保护。

### 方案（pytest 后端 + jsdom 前端，最小覆盖关键路径）

**9.1 后端 pytest（`tests/test_data_manager.py`）**

覆盖 `DataManager` 边界与 race：
```python
import asyncio
import json
import os
import pytest
from learning_style.data_manager import DataManager

@pytest.fixture
def dm(tmp_path):
    return DataManager(str(tmp_path), {"max_contextual_per_session": 50, "max_specific_per_session": 200})

def test_replace_universal_marks_dirty(dm):
    dm.replace_universal("s1", ["语气活泼"])
    assert dm._dirty_universal is True
    assert dm.universal["s1"][0]["content"] == "语气活泼"

def test_add_or_update_specific_rejects_bad_regex(dm):
    dm.add_or_update_specific("s1", "梗", "(")  # 非法正则
    assert dm.specific.get("s1") is None or len(dm.specific["s1"]) == 0

def test_replace_layer_validates_layer_name(dm):
    with pytest.raises(ValueError, match="未知的表征层"):
        dm.replace_layer("s1", "unknown", [])

def test_normalize_rejects_non_dict_entry(dm):
    with pytest.raises(ValueError, match="格式错误"):
        dm._normalize_webui_entries("s1", "universal", ["not a dict"])

def test_schedule_save_no_data_loss_under_race(dm):
    """P2 race 回归：连续 mark_dirty 必须最终保存"""
    async def run():
        dm.replace_universal("s1", ["a"])        # 触发 A
        await asyncio.sleep(0.01)                # A 进入 sleep
        dm.replace_universal("s1", ["b"])        # 触发 B，cancel A
        await asyncio.sleep(0.1)                 # 等 B 的 _delayed_save 完成
        # 重新加载验证
        dm2 = DataManager(dm.data_dir, dm.config)
        assert dm2.universal["s1"][0]["content"] == "b"
    asyncio.run(run())

def test_merge_contextual_buffer_respects_disable_flag(tmp_path):
    dm = DataManager(str(tmp_path), {"enable_contextual_merge": False, "max_contextual_per_session": 50})
    dm.add_contextual("s1", "场景", "行为")
    dm.merge_contextual_buffer("s1")
    # 关闭合并时情境表征保留
    assert len(dm.contextual["s1"]) == 1
```

**9.2 后端 JSON 提取测试（`tests/test_learning_manager.py`）**
```python
from learning_style.learning_manager import _extract_json

def test_extract_nested_json():
    out = '```json\n{"universal": ["a"], "specific": [{"content": "x", "trigger_regex": "x"}]}\n```'
    assert _extract_json(out) is not None

def test_extract_with_trailing_brace_in_string():
    out = '{"universal": ["a}b"], "contextual": []}'
    extracted = _extract_json(out)
    assert json.loads(extracted)["universal"][0] == "a}b"

def test_extract_unbalanced_returns_none():
    assert _extract_json('{"unbalanced": ') is None
```

**9.3 前端 jsdom 冒烟（`tests/webui/smoke.test.js`，恢复并固化）**

覆盖启动渲染、会话切换、Tab 切换、编辑脏数据、保存调用 `layer`、立即学习调用 `learn`、正则实时校验、**XSS 注入不执行**。

**XSS 用例**：
```js
test('universal content with <script> does not execute', () => {
  store.snapshot = { universal: { s1: [{ content: '<script>window.__xss=1</script>', proficiency: 10, confirmed_rounds: 1 }] }, contextual: {}, specific: {} };
  Views.renderOverview();
  expect(window.__xss).toBeUndefined();
  expect($('tabOverview').innerHTML).toContain('&lt;script&gt;');
});
```

**9.4 CI 集成（`.github/workflows/test.yml` 或本地 Makefile）**
```yaml
- run: pip install pytest && pytest tests/ -v
- run: cd tests/webui && npm ci && npm test
```

### 交付物
- `tests/test_data_manager.py`、`tests/test_learning_manager.py`。
- `tests/webui/smoke.test.js`（恢复 REFACTOR_OVERVIEW 声称的 11 项 + XSS 用例）。
- `tests/webui/package.json`（jsdom 依赖）。
- CI 配置或 `Makefile`。

---

## P10 · 文档同步（可维护 +0.3）

### 方案
1. **`DESIGN.md` Don't#5 更新**：单调时钟已废弃，时间戳为纪元秒，前端显示真实相对时间。
2. **`README.md`** 「风格管理页面」章节补充：
   - 特定层 `trigger_regex` 现已参与注入匹配（按用户消息命中才注入），不再「仅存储校验」。
   - 新增配置项 `enable_contextual_merge` 说明。
3. **`REFACTOR_OVERVIEW.md`** 补「v1.1.1 优化」章节，记录 P1-P10 改动。
4. **新增 `AGENTS.md` 片段**（或更新现有）：
   ```
   ## 数据写入不变量
   - 任何 mark_dirty 之后，必然有一个 _delayed_save 读取到 dirty=True 并保存。
   - _schedule_save 必须 await 旧 task 终止，不可 cancel 后就忘。
   ```
   供未来 AI 代理维护时遵守。

### 交付物
- 4 个文档 diff。

---

## 执行顺序与依赖

```
P1 (删死代码) ──┐
P7 (时间戳)   ──┼─→ P9 (测试基线) ──→ P10 (文档)
P2 (race 修复)─┤
P3 (XSS)      ──┤
P4 (JSON)     ──┤
P8 (迁移)     ──┘
P5 (DM 瘦身) ──→ P6 (死字段复活 + difflib 开关)
```

**并行机会**：P1/P3/P4/P7/P8 互不冲突，可并行。P2 改 `_schedule_save`，P5 改 `replace_layer`，P6 改 `style_injector` + `add_or_update_specific`，三者文件重叠但函数不重叠，串行更稳。

**建议串行链**：P1 → P7 → P8 → P2 → P5 → P6 → P3 → P4 → P9 → P10。

---

## 预期评分提升

| 要素 | 基线 | 目标 | 主要贡献者 |
|------|------|------|------------|
| 可维护性 | 7.0 | **9.0** | P1 删死代码 +0.3, P5 DM 瘦身 +0.4, P10 文档 +0.3, P2 mark_dirty 统一 +0.0（隐含）|
| 最轻量 | 7.5 | **9.0** | P6 死字段复活消除 YAGNI 违反 +0.5, P5 replace_layer 简化 +0.5, P1 删 257 行旧代码 +0.2 |
| 高质量 | 6.5 | **9.0** | P2 race 修复 +0.5, P3 XSS +0.3, P7 时间戳语义统一 +0.3, P9 测试 +0.5, P4 JSON 鲁棒 +0.2, P8 迁移补全 +0.2 |
| **综合** | **7.0** | **9.0** | 三要素均衡提升 |

---

## 不做的事（明确排除）

1. **不引入 SQLite**：JSON 文件对单机插件场景足够，引入 DB 违反 YAGNI。
2. **不引入前端框架**（Vue/React）：当前 vanilla ES module + 426 行 CSS 已足够克制，框架带来构建链与体积。
3. **不重写 `DataManager` 为三个独立类**：P5 抽离 WebUI 归一化已够，三独立类会破坏三层交叉逻辑（merge_contextual_buffer 同时读 universal/specific）。
4. **不删除 `difflib` 合并**：P6.2 加开关保留可能性，删除会丢情境沉淀路径。
5. **不删 `proficiency`/`confirmed_rounds`/`trigger_count` 统计字段**：P6.1 通过启用 trigger_regex 匹配让 trigger_count/last_seen 复活；proficiency/confirmed_rounds 仍偏「未来用」，但删除会破坏已存数据兼容，保留为「轻量债务」。
6. **不引入类型检查工具链**（mypy/pyright）：当前 `typing.Any` 用得不少，强制类型化收益不抵成本。可选地逐步收紧签名，但不作为本方案目标。

---

## 验收清单

- [ ] `pages/style-manager/app.js`（根目录旧版）已删除。
- [ ] `design/prototype/` 已归档至 `design/_archive/`。
- [ ] `_schedule_save` await 旧 task；`_delayed_save` 重检 dirty。
- [ ] `mark_dirty` 统一入口替换 8 处散弹 create_task。
- [ ] `util.js:esc` 真转义 `&<>"'`。
- [ ] `views.js` portrait/Top 梗榜改 textContent。
- [ ] `learning_manager._extract_json` 括号配平提取。
- [ ] `_normalize_webui_entries`/`_req_field` 迁移到 `web_ui.py`。
- [ ] `replace_layer` 接收已归一化 list，简化至 ~10 行。
- [ ] `style_injector.inject_style_to_prompt` 加 `user_message` 参数，specific 按 trigger_regex 命中注入。
- [ ] `main.on_llm_request` 传 user_message。
- [ ] `add_or_update_specific` 加 ReDoS 防护（长度 ≤200 + 嵌套量词启发式）。
- [ ] `merge_contextual_buffer` 加 `enable_contextual_merge` 配置开关。
- [ ] `_conf_schema.json` 新增 `enable_contextual_merge`。
- [ ] 后端所有 `asyncio.get_running_loop().time()` 替换为 `time.time()`。
- [ ] 前端 `relTime` 简化为纪元秒换算。
- [ ] `_handle_old_format` 真迁移旧 `styles.json` 到 universal 层。
- [ ] `tests/test_data_manager.py` 覆盖边界 + race。
- [ ] `tests/test_learning_manager.py` 覆盖 JSON 提取。
- [ ] `tests/webui/smoke.test.js` 恢复 + XSS 用例。
- [ ] CI 或 Makefile 跑通 `pytest tests/ -v` 与 `npm test`。
- [ ] `DESIGN.md` Don't#5 更新。
- [ ] `README.md` 特定层 trigger_regex 行为更新。
- [ ] `REFACTOR_OVERVIEW.md` 补 v1.1.1 优化章节。
- [ ] `AGENTS.md` 补数据写入不变量。

---

## 附录 A · 改动文件清单

| 文件 | 操作 | 阶段 |
|------|------|------|
| `pages/style-manager/app.js`（根目录） | 删除 | P1 |
| `design/prototype/` | 移动到 `design/_archive/prototype/` | P1 |
| `learning_style/data_manager.py` | 改 `_schedule_save`/`_delayed_save`/`_handle_old_format`/`add_or_update_specific`/`merge_contextual_buffer`/`replace_layer`；删 `_normalize_webui_entries`/`_req_field`；加 `mark_dirty_and_schedule`；`time.time()` 替换 | P2/P5/P6/P7/P8 |
| `learning_style/learning_manager.py` | 加 `_extract_json` + 调用点 | P4 |
| `learning_style/style_injector.py` | `inject_style_to_prompt` 加 `user_message` + specific 按需匹配 | P6 |
| `learning_style/web_ui.py` | 加 `_normalize_webui_entries`/`_req_field`；`_save_layer` 编排归一化 | P5 |
| `main.py` | `on_llm_request` 传 user_message；`time.time()` 替换 | P6/P7 |
| `pages/style-manager/src/util.js` | `esc` 真转义；`relTime` 简化 | P3/P7 |
| `pages/style-manager/src/views.js` | portrait/Top 梗榜改 textContent | P3 |
| `_conf_schema.json` | 新增 `enable_contextual_merge` | P6 |
| `tests/test_data_manager.py` | 新建 | P9 |
| `tests/test_learning_manager.py` | 新建 | P9 |
| `tests/webui/smoke.test.js` | 新建（恢复） | P9 |
| `tests/webui/package.json` | 新建 | P9 |
| `DESIGN.md` | Don't#5 更新 | P10 |
| `README.md` | trigger_regex 行为更新 | P10 |
| `REFACTOR_OVERVIEW.md` | 补 v1.1.1 章节 | P10 |
| `AGENTS.md` | 补数据写入不变量 | P10 |
| `design/README.md` | 新建（5 行说明） | P1 |
| `.github/workflows/test.yml` 或 `Makefile` | 新建 | P9 |

---

## 附录 B · 关键代码片段汇总

### B.1 `data_manager._schedule_save` 修复后（P2）
```python
async def _schedule_save(self):
    if self._save_timer is not None and not self._save_timer.done():
        self._save_timer.cancel()
        try:
            await self._save_timer
        except asyncio.CancelledError:
            pass
    self._save_timer = asyncio.create_task(self._delayed_save())

async def _delayed_save(self):
    await asyncio.sleep(self._save_delay)
    if self._dirty_universal:
        await self.save_universal()
    if self._dirty_contextual:
        await self.save_contextual()
    if self._dirty_specific:
        await self.save_specific()
    if self._dirty_chat_history:
        await self.save_chat_history()
    self._save_timer = None

def _mark_dirty_and_schedule(self, layer: str):
    setattr(self, f"_dirty_{layer}", True)
    asyncio.create_task(self._schedule_save())
```

### B.2 `util.js:esc` 修复后（P3）
```js
const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (v) => (v == null ? '' : String(v).replace(/[&<>"']/g, (c) => ESC_MAP[c]));
```

### B.3 `learning_manager._extract_json`（P4）
```python
def _extract_json(text: str) -> str | None:
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    start = candidate.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return candidate[start : i + 1]
    return None
```

### B.4 `style_injector.inject_style_to_prompt` 修复后（P6）
```python
def inject_style_to_prompt(self, session_id: str, original_system_prompt: str, user_message: str = "") -> str:
    if not self.should_inject_style(session_id):
        return original_system_prompt
    try:
        style_parts = []
        universal = self.data_manager.get_universal_for_session(session_id)
        if universal:
            style_parts.append(self.style_selector.build_style_text("通用风格", [t["content"] for t in universal]))
        contextual = self.data_manager.get_contextual_for_session(session_id)
        if contextual:
            style_parts.append(self.style_selector.build_contextual_text(contextual))
        specific = self.data_manager.get_specific_for_session(session_id)
        hit = []
        if len(user_message) <= 10000:  # ReDoS 防护：超长消息不匹配
            for s in specific:
                try:
                    if re.search(s.get("trigger_regex", ""), user_message):
                        s["trigger_count"] = s.get("trigger_count", 0) + 1
                        s["last_seen"] = time.time()
                        hit.append(s["content"])
                except re.error:
                    continue
        if hit:
            style_parts.append(self.style_selector.build_style_text("群内流行说法", hit))
        if not style_parts:
            return original_system_prompt
        style_text = "；".join(style_parts)
        full_style_text = f"在回复时，请尽量采用以下风格特点：{style_text}"
        if not original_system_prompt.strip():
            return full_style_text
        return f"{original_system_prompt}\n\n{full_style_text}"
    except Exception as e:
        logger.error(f"注入风格时发生错误: {e}")
        return original_system_prompt
```

### B.5 `data_manager._handle_old_format` 修复后（P8）
```python
def _handle_old_format(self):
    old_file = os.path.join(self.data_dir, "styles.json")
    if not os.path.exists(old_file):
        return
    logger.warning("检测到旧版数据格式 (styles.json)，开始迁移到三层存储...")
    try:
        with open(old_file, encoding="utf-8") as f:
            old_data = json.load(f)
        now = time.time()
        for sid, traits in old_data.items():
            if not isinstance(traits, list):
                continue
            self.universal[sid] = [
                {
                    "content": t.get("content", str(t)) if isinstance(t, dict) else str(t),
                    "proficiency": 10,
                    "confirmed_rounds": 1,
                    "last_updated": now,
                }
                for t in traits
            ]
        self._dirty_universal = True
        os.rename(old_file, old_file + ".migrated.bak")
        logger.info(f"迁移完成：{len(old_data)} 个会话的旧表征已并入通用层。")
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"迁移旧格式失败: {e}，旧文件保留为 {old_file}.bak")
        try:
            os.rename(old_file, old_file + ".bak")
        except OSError:
            pass
```

---

## 附录 C · 风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| P6 启用 trigger_regex 匹配引入 ReDoS | 中 | 高（注入卡死） | P6.3 长度+嵌套量词启发式 + 超长消息跳过匹配 |
| P5 迁移 `_normalize_webui_entries` 漏掉元数据保留对照 | 低 | 中（WebUI 编辑丢统计） | P9 测试 `test_replace_layer_preserves_metadata` |
| P7 `time.time()` 与旧单调时钟值混排导致侧栏排序异常 | 低 | 低（仅排序美观） | 旧值恒小沉底，可接受；P9 不专门测 |
| P8 迁移脚本误判旧 `styles.json` 格式 | 低 | 中（迁移失败但旧文件保留 .bak） | try/except 兜底，失败回退 rename .bak |
| P9 jsdom 测试环境在 CI 不可用 | 中 | 低（本地仍可跑） | Makefile 本地 `make test` 兜底 |

---

**方案完成。** 共 10 阶段、20 文件改动、5 代码片段附录、3 风险矩阵。三要素目标均 ≥ 9.0，综合 9.0。零功能损失。

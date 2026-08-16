import asyncio
import difflib
import json
import os
import re
import time
from typing import Any

from astrbot.api import logger


# 情境表征缓冲比例（硬编码）
CONTEXTUAL_BUFFER_RATIO = 0.2  # 20% 为缓冲位

# WebUI 整层替换时的通用表征上限（与 LLM 提示词的"最多10条"契约一致）
MAX_UNIVERSAL_PER_SESSION = 10


class DataManager:
    """
    三层表征管理：
    - 通用（universal）：稳定风格基调，LLM 全量重写
    - 情境（contextual）：场景→行为模式，FIFO 容量管理 + 缓冲合并
    - 特定（specific）：梗+释义，trigger_regex 匹配
    """

    def __init__(self, data_dir: str, config: dict):
        self.data_dir = data_dir
        self.universal_file = os.path.join(data_dir, "universal.json")
        self.contextual_file = os.path.join(data_dir, "contextual.json")
        self.specific_file = os.path.join(data_dir, "specific.json")
        self.chat_history_file = os.path.join(data_dir, "chat_history.json")

        self.universal: dict[str, list[dict[str, Any]]] = {}
        self.contextual: dict[str, list[dict[str, Any]]] = {}
        self.specific: dict[str, list[dict[str, Any]]] = {}
        self.chat_history: dict[str, list[dict[str, Any]]] = {}

        self.config = config

        self._ensure_data_dir()
        self.load_universal()
        self.load_contextual()
        self.load_specific()
        self.load_chat_history()
        self.lock = asyncio.Lock()

        self._dirty_universal = False
        self._dirty_contextual = False
        self._dirty_specific = False
        self._dirty_chat_history = False
        self._save_timer = None
        self._save_delay = 5.0
        # 迁移旧格式须在 load_* 与 dirty 清零之后，
        # 迁移写入的 universal 不会被空文件加载覆盖，dirty 标志也不会被清。
        self._handle_old_format()

    def _ensure_data_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            logger.info(f"创建数据目录: {self.data_dir}")

    def _handle_old_format(self):
        """检测旧版 styles.json，迁移为三层存储。

        旧格式：{session_id: [trait, ...]}，无三层区分。
        迁移策略：全部并入 universal 层作为初始基色，
        用户可在 WebUI 重新分类。迁移成功后备份为
        styles.json.migrated.bak，失败回退 .bak。
        """
        old_file = os.path.join(self.data_dir, "styles.json")
        if not os.path.exists(old_file):
            return
        logger.warning("检测到旧版数据格式 (styles.json)，开始迁移到三层存储...")
        try:
            with open(old_file, encoding="utf-8") as f:
                old_data = json.load(f)
            if not isinstance(old_data, dict):
                raise ValueError("旧格式根对象应为 dict")
            now = time.time()
            migrated = 0
            for sid, traits in old_data.items():
                if not isinstance(traits, list):
                    continue
                self.universal[sid] = [
                    {
                        "content": (
                            t.get("content", str(t))
                            if isinstance(t, dict)
                            else str(t)
                        ),
                        "proficiency": 10,
                        "confirmed_rounds": 1,
                        "last_updated": now,
                    }
                    for t in traits
                ]
                migrated += 1
            self._dirty_universal = True
            os.rename(old_file, old_file + ".migrated.bak")
            logger.info(
                f"迁移完成：{migrated} 个会话的旧表征已并入通用层，"
                f"旧文件备份为 styles.json.migrated.bak。"
            )
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.error(f"迁移旧格式失败: {e}，旧文件保留为 styles.json.bak")
            try:
                os.rename(old_file, old_file + ".bak")
            except OSError:
                pass

    # ==================== 通用表征 ====================

    def load_universal(self):
        if os.path.exists(self.universal_file):
            try:
                with open(self.universal_file, encoding="utf-8") as f:
                    self.universal = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"加载通用表征文件失败: {e}")
                self.universal = {}
        else:
            self.universal = {}

    def get_universal_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return self.universal.get(session_id, [])

    def replace_universal(self, session_id: str, contents: list[str]):
        """
        全量替换通用表征。
        - 延续的表征 proficiency +5，confirmed_rounds +1
        - 新增的表征 proficiency=10，confirmed_rounds=1
        """
        current_time = time.time()
        old_map = {}
        for trait in self.universal.get(session_id, []):
            old_map[trait["content"]] = trait

        new_traits = []
        for content in contents:
            if content in old_map:
                old = old_map[content]
                new_traits.append({
                    "content": content,
                    "proficiency": min(100, old.get("proficiency", 0) + 5),
                    "confirmed_rounds": old.get("confirmed_rounds", 0) + 1,
                    "last_updated": current_time,
                })
            else:
                new_traits.append({
                    "content": content,
                    "proficiency": 10,
                    "confirmed_rounds": 1,
                    "last_updated": current_time,
                })

        self.universal[session_id] = new_traits
        self._mark_dirty_and_schedule("universal")

    async def save_universal(self):
        async with self.lock:
            try:
                with open(self.universal_file, "w", encoding="utf-8") as f:
                    json.dump(self.universal, f, ensure_ascii=False, indent=4)
                self._dirty_universal = False
            except OSError as e:
                logger.error(f"保存通用表征文件失败: {e}")

    # ==================== 情境表征 ====================

    def load_contextual(self):
        if os.path.exists(self.contextual_file):
            try:
                with open(self.contextual_file, encoding="utf-8") as f:
                    self.contextual = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"加载情境表征文件失败: {e}")
                self.contextual = {}
        else:
            self.contextual = {}

    def get_contextual_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return self.contextual.get(session_id, [])

    def get_contextual_buffer(self, session_id: str) -> list[dict[str, Any]]:
        """仅返回缓冲位中的情境表征（供维护合并用）。"""
        return [
            t
            for t in self.contextual.get(session_id, [])
            if t.get("_in_buffer")
        ]

    def add_contextual(self, session_id: str, scene: str, behavior: str):
        """
        添加情境表征。
        - FIFO 添加，标记为缓冲位
        - 超容量 50 时淘汰最早的
        - 自动调整缓冲位标记（最新 20% 为缓冲）
        """
        current_time = time.time()
        if session_id not in self.contextual:
            self.contextual[session_id] = []

        self.contextual[session_id].append({
            "scene": scene,
            "behavior": behavior,
            "created_at": current_time,
            "_in_buffer": True,
        })

        # FIFO 容量检查
        max_capacity = self.config.get("max_contextual_per_session", 50)
        while len(self.contextual[session_id]) > max_capacity:
            removed = self.contextual[session_id].pop(0)
            logger.debug(
                f"FIFO 淘汰情境表征: {removed.get('scene', '?')}→{removed.get('behavior', '?')}"
            )

        # 重新标记缓冲位（最新 20%）
        self._refresh_buffer_markers(session_id)
        self._mark_dirty_and_schedule("contextual")

    def _refresh_buffer_markers(self, session_id: str):
        """重新计算并标记情境表征的缓冲位。"""
        traits = self.contextual.get(session_id, [])
        if not traits:
            return
        buffer_count = max(1, int(len(traits) * CONTEXTUAL_BUFFER_RATIO))
        for i, t in enumerate(traits):
            t["_in_buffer"] = (i >= len(traits) - buffer_count)

    def mark_contextual_merged(self, session_id: str, index: int):
        """从情境列表中移除已合并的条目。"""
        if session_id in self.contextual and 0 <= index < len(self.contextual[session_id]):
            self.contextual[session_id].pop(index)
            self._refresh_buffer_markers(session_id)
            self._mark_dirty_and_schedule("contextual")

    def merge_contextual_buffer(self, session_id: str, threshold: float = 0.85):
        """
        将缓冲位的情境表征尝试合并到通用/特定。
        遍历缓冲条目，按 scene→behavior 文本相似度：
        1. 跟通用比对 → 匹配则合并proficiency，从情境移除
        2. 跟特定比对 → 匹配则合并trigger_count，从情境移除
        3. 都不匹配 → 留在缓冲

        配置 enable_contextual_merge=false 时跳过合并，
        情境表征仅按 FIFO 淘汰。
        """
        if not self.config.get("enable_contextual_merge", True):
            return
        if session_id not in self.contextual:
            return

        remaining = []
        for item in self.contextual[session_id]:
            if not item.get("_in_buffer"):
                remaining.append(item)
                continue

            text = f"{item['scene']}→{item['behavior']}"
            merged = False

            # 尝试合并到通用
            if session_id in self.universal:
                for u in self.universal[session_id]:
                    score = difflib.SequenceMatcher(None, text, u["content"]).ratio()
                    if score > threshold:
                        u["proficiency"] = min(100, u.get("proficiency", 0) + 5)
                        merged = True
                        logger.debug(f"情境 '{text}' 合并到通用 '{u['content']}'")
                        break

            if merged:
                continue

            # 尝试合并到特定
            if session_id in self.specific:
                for s in self.specific[session_id]:
                    score = difflib.SequenceMatcher(
                        None, text, s["content"]
                    ).ratio()
                    if score > threshold:
                        s["trigger_count"] = s.get("trigger_count", 0) + 1
                        merged = True
                        logger.debug(f"情境 '{text}' 合并到特定 '{s['content']}'")
                        break

            if not merged:
                remaining.append(item)

        self.contextual[session_id] = remaining
        self._refresh_buffer_markers(session_id)
        self._mark_dirty_and_schedule("contextual")

    async def save_contextual(self):
        async with self.lock:
            try:
                with open(self.contextual_file, "w", encoding="utf-8") as f:
                    json.dump(self.contextual, f, ensure_ascii=False, indent=4)
                self._dirty_contextual = False
            except OSError as e:
                logger.error(f"保存情境表征文件失败: {e}")

    # ==================== 特定表征 ====================

    def load_specific(self):
        if os.path.exists(self.specific_file):
            try:
                with open(self.specific_file, encoding="utf-8") as f:
                    self.specific = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"加载特定表征文件失败: {e}")
                self.specific = {}
        else:
            self.specific = {}

    def get_specific_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return self.specific.get(session_id, [])

    def add_or_update_specific(
        self, session_id: str, content: str, trigger_regex: str
    ):
        # ReDoS 防护：限制正则长度，拒绝嵌套量词
        if len(trigger_regex) > 200:
            logger.error(
                f"特定表征 '{content}' 的正则过长 (>200 字符)，拒绝存储"
            )
            return
        if re.search(r"\([^()]*[+*?][^()]*\)[+*?]", trigger_regex):
            logger.error(
                f"特定表征 '{content}' 的正则含嵌套量词，可能 ReDoS，拒绝存储"
            )
            return
        try:
            re.compile(trigger_regex)
        except re.error as e:
            logger.error(
                f"特定表征 '{content}' 的正则表达式无效: {trigger_regex}, 错误: {e}"
            )
            return

        current_time = time.time()
        if session_id not in self.specific:
            self.specific[session_id] = []

        for trait in self.specific[session_id]:
            if trait["content"] == content:
                trait["trigger_count"] = trait.get("trigger_count", 0) + 1
                trait["last_seen"] = current_time
                self._mark_dirty_and_schedule("specific")
                return

        self.specific[session_id].append({
            "content": content,
            "trigger_regex": trigger_regex,
            "trigger_count": 1,
            "first_seen": current_time,
            "last_seen": current_time,
        })
        self._mark_dirty_and_schedule("specific")

    def remove_lowest_specific(self, session_id: str, count: int):
        if session_id not in self.specific or count <= 0:
            return
        traits = sorted(
            self.specific[session_id], key=lambda t: t.get("trigger_count", 0)
        )
        self.specific[session_id] = traits[count:]
        self._mark_dirty_and_schedule("specific")

    def check_specific_capacity(self, session_id: str):
        max_specific = self.config.get("max_specific_per_session", 200)
        if session_id in self.specific and len(self.specific[session_id]) > max_specific:
            excess = len(self.specific[session_id]) - max_specific
            self.remove_lowest_specific(session_id, excess)

    async def save_specific(self):
        async with self.lock:
            try:
                with open(self.specific_file, "w", encoding="utf-8") as f:
                    json.dump(self.specific, f, ensure_ascii=False, indent=4)
                self._dirty_specific = False
            except OSError as e:
                logger.error(f"保存特定表征文件失败: {e}")

    # ==================== 公共保存逻辑 ====================

    def _mark_dirty_and_schedule(self, layer: str) -> None:
        """统一入口：标记层脏 + 调度延迟保存。

        关键不变量：本方法必然触发一次 _delayed_save，
        且该次保存执行前会重新读取 dirty 标志——
        即使前一个 save task 已把 dirty 清掉，
        本次的 mark_dirty 在 save 启动前已完成，
        故 save 必能看到并保存本次变更。
        """
        setattr(self, f"_dirty_{layer}", True)
        asyncio.create_task(self._schedule_save())

    async def _schedule_save(self) -> None:
        """调度一次延迟保存；若有 pending task 先 await 其终止。

        await 旧 task 的目的：消除「cancel 后就忘」造成的
        dirty 标志被半完成的旧 save 错误清零的 race。
        旧 task 被 cancel 时 _delayed_save 抛 CancelledError，
        dirty 标志保持原值，下一个 _delayed_save 会重新处理。
        """
        if self._save_timer is not None and not self._save_timer.done():
            self._save_timer.cancel()
            try:
                await self._save_timer
            except asyncio.CancelledError:
                pass
        self._save_timer = asyncio.create_task(self._delayed_save())

    async def _delayed_save(self) -> None:
        await asyncio.sleep(self._save_delay)
        # 重新读取 dirty：期间若有新 mark_dirty，dirty 仍为 True
        if self._dirty_universal:
            await self.save_universal()
        if self._dirty_contextual:
            await self.save_contextual()
        if self._dirty_specific:
            await self.save_specific()
        if self._dirty_chat_history:
            await self.save_chat_history()
        self._save_timer = None

    async def force_save(self) -> None:
        if self._save_timer is not None and not self._save_timer.done():
            self._save_timer.cancel()
            try:
                await self._save_timer
            except asyncio.CancelledError:
                pass
            self._save_timer = None
        if self._dirty_universal:
            await self.save_universal()
        if self._dirty_contextual:
            await self.save_contextual()
        if self._dirty_specific:
            await self.save_specific()
        if self._dirty_chat_history:
            await self.save_chat_history()

    # ==================== 聊天记录 ====================

    def load_chat_history(self):
        if os.path.exists(self.chat_history_file):
            try:
                with open(self.chat_history_file, encoding="utf-8") as f:
                    self.chat_history = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"加载聊天记录文件失败: {e}")
                self.chat_history = {}
        else:
            self.chat_history = {}

    async def save_chat_history(self):
        async with self.lock:
            try:
                with open(self.chat_history_file, "w", encoding="utf-8") as f:
                    json.dump(self.chat_history, f, ensure_ascii=False, indent=4)
                self._dirty_chat_history = False
            except OSError as e:
                logger.error(f"保存聊天记录文件失败: {e}")

    async def add_message_to_history(self, session_id: str, message: dict[str, Any]):
        if session_id not in self.chat_history:
            self.chat_history[session_id] = []
        self.chat_history[session_id].append(message)
        self._dirty_chat_history = True
        await self._schedule_save()

    def get_chat_history(
        self, session_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        return self.chat_history.get(session_id, [])[-limit:]

    async def clear_chat_history(self, session_id: str):
        if session_id in self.chat_history:
            self.chat_history[session_id] = []
            self._dirty_chat_history = True
            await self._schedule_save()

    # ==================== WebUI 管理 ====================

    def get_snapshot(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """返回三层表征的实时快照（供 WebUI 展示）。"""
        return {
            "universal": self.universal,
            "contextual": self.contextual,
            "specific": self.specific,
        }

    def global_stats(self) -> dict[str, Any]:
        """返回全局统计（供 WebUI 顶栏与总览展示）。"""
        sids: set[str] = set()
        for layer in (self.universal, self.contextual, self.specific):
            sids.update(layer.keys())
        total_entries = (
            sum(len(v) for v in self.universal.values())
            + sum(len(v) for v in self.contextual.values())
            + sum(len(v) for v in self.specific.values())
        )
        return {
            "total_sessions": len(sids),
            "total_entries": total_entries,
            "injection_enabled": self.config.get("enable_style_injection", True),
            "caps": {
                "universal": MAX_UNIVERSAL_PER_SESSION,
                "contextual": self.config.get("max_contextual_per_session", 150),
                "specific": self.config.get("max_specific_per_session", 200),
            },
        }

    def clear_session(self, session_id: str) -> None:
        """清空某会话的全部三层表征（不改变聊天记录）。"""
        if session_id in self.universal:
            self.universal[session_id] = []
            self._dirty_universal = True
        if session_id in self.contextual:
            self.contextual[session_id] = []
            self._dirty_contextual = True
        if session_id in self.specific:
            self.specific[session_id] = []
            self._mark_dirty_and_schedule("specific")

    def export_session(self, session_id: str) -> dict[str, Any]:
        """导出某会话的三层表征（供 WebUI 下载，剔除内部缓冲标记）。"""
        contextual = [
            {k: v for k, v in entry.items() if k != "_in_buffer"}
            for entry in self.get_contextual_for_session(session_id)
        ]
        return {
            "sid": session_id,
            "universal": self.get_universal_for_session(session_id),
            "contextual": contextual,
            "specific": self.get_specific_for_session(session_id),
        }

    def replace_layer(self, session_id: str, layer: str, normalized: list[dict[str, Any]]):
        """整层替换某会话的表征（供 WebUI 保存）。

        调用方（web_ui.normalize_webui_entries）已完成校验与元数据保留，
        本方法仅做写入与脏标记。
        """
        if layer == "universal":
            self.universal[session_id] = normalized
            self._mark_dirty_and_schedule("universal")
        elif layer == "contextual":
            self.contextual[session_id] = normalized
            self._refresh_buffer_markers(session_id)
            self._mark_dirty_and_schedule("contextual")
        else:
            self.specific[session_id] = normalized
            self._mark_dirty_and_schedule("specific")

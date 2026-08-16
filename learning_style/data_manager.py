import asyncio
import copy
import difflib
import hashlib
import json
import os
import shutil
import time
from functools import lru_cache
from typing import Any

import regex
from astrbot.api import logger

# 情境表征缓冲比例（硬编码）
CONTEXTUAL_BUFFER_RATIO = 0.2  # 20% 为缓冲位

# WebUI 整层替换时的通用表征上限（与 LLM 提示词的"最多10条"契约一致）
MAX_UNIVERSAL_PER_SESSION = 10

# 各层容量默认值（与 _conf_schema.json 保持一致，避免多处 fallback 分歧）
MAX_CONTEXTUAL_PER_SESSION = 150
MAX_SPECIFIC_PER_SESSION = 200

# 每会话聊天记录保留上限（分析窗口为最近 100 条，500 足够覆盖）
MAX_CHAT_HISTORY_PER_SESSION = 500
MAX_TRIGGER_PATTERN_LENGTH = 200
MAX_MATCH_MESSAGE_LENGTH = 10000
PER_PATTERN_TIMEOUT_SECONDS = 0.01
TOTAL_MATCH_BUDGET_SECONDS = 0.05

LAYERS = ("universal", "contextual", "specific", "chat_history")


@lru_cache(maxsize=512)
def _compile_trigger(pattern: str):
    return regex.compile(pattern)


class RevisionConflictError(ValueError):
    pass


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
        self.transaction_file = os.path.join(data_dir, ".save-transaction.json")
        self._layer_files = {
            "universal": self.universal_file,
            "contextual": self.contextual_file,
            "specific": self.specific_file,
            "chat_history": self.chat_history_file,
        }

        self.universal: dict[str, list[dict[str, Any]]] = {}
        self.contextual: dict[str, list[dict[str, Any]]] = {}
        self.specific: dict[str, list[dict[str, Any]]] = {}
        self.chat_history: dict[str, list[dict[str, Any]]] = {}

        self.config = config
        self.max_contextual_per_session = self._positive_int_config(
            "max_contextual_per_session", MAX_CONTEXTUAL_PER_SESSION
        )
        self.max_specific_per_session = self._positive_int_config(
            "max_specific_per_session", MAX_SPECIFIC_PER_SESSION
        )
        self.enable_contextual_merge = self._bool_config(
            "enable_contextual_merge", True
        )
        self.enable_style_injection = self._bool_config(
            "enable_style_injection", True
        )

        self._save_lock = asyncio.Lock()
        self._dirty: set[str] = set()
        self._save_timer: asyncio.Task | None = None
        self._save_delay = 5.0

        self._ensure_data_dir()
        self._recover_save_transaction()
        for layer, path in self._layer_files.items():
            self._recover_atomic_temp(layer, path)
        self.load_universal()
        self.load_contextual()
        self.load_specific()
        self.load_chat_history()
        self._handle_old_format()

    def _positive_int_config(self, key: str, default: int) -> int:
        value = self.config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            logger.warning(f"配置 {key} 必须是正整数，已回退为 {default}。")
            return default
        return value

    def _bool_config(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        if not isinstance(value, bool):
            logger.warning(f"配置 {key} 必须是布尔值，已回退为 {default}。")
            return default
        return value

    def _ensure_data_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            logger.info(f"创建数据目录: {self.data_dir}")

    def _handle_old_format(self):
        """检测旧版 styles.json，迁移为三层存储。

        旧格式：{session_id: [trait, ...]}，无三层区分。
        迁移策略：全部并入 universal 层作为初始基色，
        用户可在 WebUI 重新分类。目标文件落盘后才备份源文件。
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
            migrated_store = copy.deepcopy(self.universal)
            for sid, traits in old_data.items():
                if not isinstance(sid, str) or not sid.strip():
                    raise ValueError("旧格式会话 ID 必须是非空字符串")
                if not isinstance(traits, list):
                    raise ValueError("旧格式会话内容必须是 list")
                normalized = []
                for trait in traits:
                    content = trait.get("content") if isinstance(trait, dict) else trait
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError("旧格式表征必须是非空字符串")
                    normalized.append({
                        "content": content,
                        "proficiency": 10,
                        "confirmed_rounds": 1,
                        "last_updated": now,
                    })
                migrated_store[sid] = normalized

            self._write_json_atomic(self.universal_file, migrated_store)
            self.universal = migrated_store
            os.replace(old_file, old_file + ".migrated.bak")
            logger.info(
                f"迁移完成：{len(old_data)} 个会话的旧表征已并入通用层，"
                f"旧文件备份为 styles.json.migrated.bak。"
            )
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.error(f"迁移旧格式失败: {e}，源文件保持不变。")

    # ==================== 通用加载/保存 ====================

    @staticmethod
    def _nonnegative_number(value: Any, default: int | float) -> int | float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return default
        return value

    def _normalize_entry(self, layer: str, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        if layer == "universal":
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                return None
            return {
                "content": content,
                "proficiency": self._nonnegative_number(
                    item.get("proficiency"), 10
                ),
                "confirmed_rounds": self._nonnegative_number(
                    item.get("confirmed_rounds"), 1
                ),
                "last_updated": self._nonnegative_number(
                    item.get("last_updated"), 0
                ),
            }
        if layer == "contextual":
            scene = item.get("scene")
            behavior = item.get("behavior")
            if not isinstance(scene, str) or not scene.strip():
                return None
            if not isinstance(behavior, str) or not behavior.strip():
                return None
            return {
                "scene": scene,
                "behavior": behavior,
                "created_at": self._nonnegative_number(item.get("created_at"), 0),
                "_in_buffer": item.get("_in_buffer", False)
                if isinstance(item.get("_in_buffer", False), bool)
                else False,
            }
        if layer == "specific":
            content = item.get("content")
            trigger_regex = item.get("trigger_regex")
            if not isinstance(content, str) or not content.strip():
                return None
            try:
                self.validate_trigger_regex(trigger_regex)
            except ValueError:
                return None
            return {
                "content": content,
                "trigger_regex": trigger_regex,
                "trigger_count": self._nonnegative_number(
                    item.get("trigger_count"), 1
                ),
                "first_seen": self._nonnegative_number(item.get("first_seen"), 0),
                "last_seen": self._nonnegative_number(item.get("last_seen"), 0),
            }
        sender = item.get("sender")
        content = item.get("content")
        if not isinstance(sender, str) or not isinstance(content, str):
            return None
        return {
            "sender": sender,
            "content": content,
            "timestamp": self._nonnegative_number(item.get("timestamp"), 0),
        }

    def _normalize_store(
        self, layer: str, raw: Any
    ) -> tuple[dict[str, list[dict[str, Any]]], bool]:
        if not isinstance(raw, dict):
            raise ValueError("root must be an object")
        cleaned: dict[str, list[dict[str, Any]]] = {}
        changed = False
        for session_id, entries in raw.items():
            if not isinstance(session_id, str) or not session_id.strip():
                raise ValueError("session ID must be a non-empty string")
            if not isinstance(entries, list):
                raise ValueError("session value must be a list")
            normalized_entries = []
            for index, item in enumerate(entries):
                normalized = self._normalize_entry(layer, item)
                if normalized is None:
                    changed = True
                    logger.warning(
                        f"加载 {layer} 时跳过无效条目: index={index}"
                    )
                    continue
                normalized_entries.append(normalized)
                if normalized != item:
                    changed = True
            cleaned[session_id] = normalized_entries
        return cleaned, changed

    def _corrupt_backup_path(self, path: str) -> str:
        stamp = int(time.time() * 1000)
        backup = f"{path}.corrupt.{stamp}.bak"
        while os.path.exists(backup):
            stamp += 1
            backup = f"{path}.corrupt.{stamp}.bak"
        return backup

    def _load_layer(self, path: str, attr: str) -> None:
        if not os.path.exists(path):
            setattr(self, attr, {})
            return
        try:
            with open(path, encoding="utf-8") as file:
                raw = json.load(file)
            cleaned, changed = self._normalize_store(attr, raw)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.error(f"加载 {attr} 失败: {exc}")
            try:
                os.replace(path, self._corrupt_backup_path(path))
            except OSError as backup_error:
                logger.error(f"备份损坏的 {attr} 文件失败: {backup_error}")
            setattr(self, attr, {})
            return

        setattr(self, attr, cleaned)
        if changed:
            try:
                shutil.copy2(path, self._corrupt_backup_path(path))
                self._write_json_atomic(path, cleaned)
            except OSError as exc:
                logger.error(f"清理 {attr} 文件失败: {exc}")

    def _is_valid_layer_file(self, layer: str, path: str) -> bool:
        try:
            with open(path, encoding="utf-8") as file:
                raw = json.load(file)
            cleaned, _ = self._normalize_store(layer, raw)
            return all(
                len(cleaned[session_id]) == len(entries)
                for session_id, entries in raw.items()
            )
        except (OSError, json.JSONDecodeError, ValueError):
            return False

    def _recover_atomic_temp(self, layer: str, path: str) -> None:
        tmp_path = f"{path}.tmp"
        if not os.path.exists(tmp_path):
            return
        try:
            if os.path.exists(path) and self._is_valid_layer_file(layer, path):
                os.remove(tmp_path)
            elif self._is_valid_layer_file(layer, tmp_path):
                os.replace(tmp_path, path)
                logger.warning(f"已从临时文件恢复 {layer}。")
            else:
                os.remove(tmp_path)
        except OSError as exc:
            logger.error(f"处理 {layer} 临时文件失败: {exc}")

    @staticmethod
    def _file_hash(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            for chunk in iter(lambda: file.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_json_file(path: str, data: Any) -> None:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
            file.flush()
            os.fsync(file.fileno())

    def _write_json_atomic(self, path: str, data: Any) -> None:
        tmp_path = f"{path}.tmp"
        try:
            self._write_json_file(tmp_path, data)
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _remove_orphan_transaction_temps(self) -> None:
        for target in self._layer_files.values():
            prefix = os.path.basename(target) + ".txn."
            for name in os.listdir(self.data_dir):
                if name.startswith(prefix) and name.endswith(".tmp"):
                    try:
                        os.remove(os.path.join(self.data_dir, name))
                    except OSError:
                        pass

    def _recover_save_transaction(self) -> bool:
        if not os.path.exists(self.transaction_file):
            journal_tmp = f"{self.transaction_file}.tmp"
            if os.path.exists(journal_tmp):
                try:
                    os.remove(journal_tmp)
                except OSError:
                    pass
            self._remove_orphan_transaction_temps()
            return True
        try:
            with open(self.transaction_file, encoding="utf-8") as file:
                manifest = json.load(file)
            entries = manifest.get("entries") if isinstance(manifest, dict) else None
            if not isinstance(entries, list) or not entries:
                raise ValueError("invalid transaction manifest")
            allowed_targets = {
                os.path.basename(path): path for path in self._layer_files.values()
            }
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("invalid transaction entry")
                target_name = entry.get("target")
                temp_name = entry.get("temp")
                expected_hash = entry.get("sha256")
                if target_name not in allowed_targets:
                    raise ValueError("unknown transaction target")
                if (
                    not isinstance(temp_name, str)
                    or os.path.basename(temp_name) != temp_name
                    or not isinstance(expected_hash, str)
                ):
                    raise ValueError("invalid transaction path or hash")
                target = allowed_targets[target_name]
                temp = os.path.join(self.data_dir, temp_name)
                if os.path.exists(temp) and self._file_hash(temp) == expected_hash:
                    os.replace(temp, target)
                elif not (
                    os.path.exists(target)
                    and self._file_hash(target) == expected_hash
                ):
                    raise ValueError("transaction data is missing or corrupted")
            os.remove(self.transaction_file)
            self._remove_orphan_transaction_temps()
            logger.warning("已完成中断的多文件保存事务。")
            return True
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.error(f"恢复多文件保存事务失败: {exc}")
            return False

    # ==================== 通用表征 ====================

    def load_universal(self):
        self._load_layer(self.universal_file, "universal")

    def get_universal_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self.universal.get(session_id, []))

    def replace_universal(self, session_id: str, contents: list[str]):
        """
        全量替换通用表征。
        - 延续的表征 proficiency +5，confirmed_rounds +1
        - 新增的表征 proficiency=10，confirmed_rounds=1
        """
        self.universal[session_id] = self._build_universal_traits(
            session_id, contents
        )
        self._mark_dirty("universal")

    def _build_universal_traits(
        self, session_id: str, contents: list[str]
    ) -> list[dict[str, Any]]:
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

        return new_traits

    async def save_universal(self) -> bool:
        return await self._save_layers({"universal"})

    # ==================== 情境表征 ====================

    def load_contextual(self):
        self._load_layer(self.contextual_file, "contextual")

    def get_contextual_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self.contextual.get(session_id, []))

    def get_contextual_buffer(self, session_id: str) -> list[dict[str, Any]]:
        """仅返回缓冲位中的情境表征（供维护合并用）。"""
        return copy.deepcopy([
            t
            for t in self.contextual.get(session_id, [])
            if t.get("_in_buffer")
        ])

    def get_learning_context(self, session_id: str) -> dict[str, Any]:
        return {
            "universal": self.get_universal_for_session(session_id),
            "contextual_buffer": self.get_contextual_buffer(session_id),
        }

    def add_contextual(self, session_id: str, scene: str, behavior: str):
        """
        添加情境表征。
        - FIFO 添加，标记为缓冲位
        - 超容量时淘汰最早的
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
        max_capacity = self.max_contextual_per_session
        while len(self.contextual[session_id]) > max_capacity:
            self.contextual[session_id].pop(0)
            logger.debug("FIFO 淘汰一条情境表征")

        # 重新标记缓冲位（最新 20%）
        self._refresh_buffer_markers(session_id)
        self._mark_dirty("contextual")

    def _refresh_buffer_markers(self, session_id: str):
        """重新计算并标记情境表征的缓冲位。"""
        traits = self.contextual.get(session_id, [])
        self._set_buffer_markers(traits)

    @staticmethod
    def _set_buffer_markers(traits: list[dict[str, Any]]) -> None:
        if not traits:
            return
        buffer_count = max(1, int(len(traits) * CONTEXTUAL_BUFFER_RATIO))
        for i, t in enumerate(traits):
            t["_in_buffer"] = (i >= len(traits) - buffer_count)

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
        if not self.enable_contextual_merge:
            return
        if session_id not in self.contextual:
            return

        original_contextual = self.contextual[session_id]
        original_universal = self.universal.get(session_id, [])
        original_specific = self.specific.get(session_id, [])
        universal = copy.deepcopy(original_universal)
        specific = copy.deepcopy(original_specific)
        remaining = []
        for item in copy.deepcopy(original_contextual):
            if not item.get("_in_buffer"):
                remaining.append(item)
                continue

            text = f"{item['scene']}→{item['behavior']}"
            merged = False

            # 尝试合并到通用
            if universal:
                for u in universal:
                    score = difflib.SequenceMatcher(None, text, u["content"]).ratio()
                    if score > threshold:
                        u["proficiency"] = min(100, u.get("proficiency", 0) + 5)
                        merged = True
                        logger.debug("一条情境表征已合并到通用层")
                        break

            if merged:
                continue

            # 尝试合并到特定
            if specific:
                for s in specific:
                    score = difflib.SequenceMatcher(
                        None, text, s["content"]
                    ).ratio()
                    if score > threshold:
                        s["trigger_count"] = s.get("trigger_count", 0) + 1
                        merged = True
                        logger.debug("一条情境表征已合并到特定层")
                        break

            if not merged:
                remaining.append(item)

        self._set_buffer_markers(remaining)
        changed_layers = []
        if remaining != original_contextual:
            self.contextual[session_id] = remaining
            changed_layers.append("contextual")
        if universal != original_universal:
            self.universal[session_id] = universal
            changed_layers.append("universal")
        if specific != original_specific:
            self.specific[session_id] = specific
            changed_layers.append("specific")
        if changed_layers:
            self._mark_dirty(*changed_layers)

    async def save_contextual(self) -> bool:
        return await self._save_layers({"contextual"})

    # ==================== 特定表征 ====================

    def load_specific(self):
        self._load_layer(self.specific_file, "specific")

    def get_specific_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self.specific.get(session_id, []))

    def get_session_layers(self, session_id: str) -> dict[str, list[dict[str, Any]]]:
        return {
            "universal": self.get_universal_for_session(session_id),
            "contextual": self.get_contextual_for_session(session_id),
            "specific": self.get_specific_for_session(session_id),
        }

    def add_or_update_specific(
        self, session_id: str, content: str, trigger_regex: str
    ):
        try:
            self.validate_trigger_regex(trigger_regex)
        except ValueError as exc:
            logger.warning(f"拒绝存储无效特定表征正则: {exc}")
            return

        current_time = time.time()
        if session_id not in self.specific:
            self.specific[session_id] = []

        for trait in self.specific[session_id]:
            if trait["content"] == content:
                trait["trigger_count"] = trait.get("trigger_count", 0) + 1
                trait["last_seen"] = current_time
                self._mark_dirty("specific")
                return

        self.specific[session_id].append({
            "content": content,
            "trigger_regex": trigger_regex,
            "trigger_count": 1,
            "first_seen": current_time,
            "last_seen": current_time,
        })
        self._mark_dirty("specific")

    def remove_lowest_specific(self, session_id: str, count: int):
        if session_id not in self.specific or count <= 0:
            return
        traits = sorted(
            self.specific[session_id], key=lambda t: t.get("trigger_count", 0)
        )
        self.specific[session_id] = traits[count:]
        self._mark_dirty("specific")

    def check_specific_capacity(self, session_id: str):
        max_specific = self.max_specific_per_session
        if session_id in self.specific and len(self.specific[session_id]) > max_specific:
            excess = len(self.specific[session_id]) - max_specific
            self.remove_lowest_specific(session_id, excess)

    @staticmethod
    def validate_trigger_regex(trigger_regex: str) -> None:
        if not isinstance(trigger_regex, str) or not trigger_regex.strip():
            raise ValueError("trigger_regex must be a non-empty string")
        if len(trigger_regex) > MAX_TRIGGER_PATTERN_LENGTH:
            raise ValueError(
                f"trigger_regex exceeds {MAX_TRIGGER_PATTERN_LENGTH} characters"
            )
        if regex.search(r"\([^()]*[+*?][^()]*\)[+*?]", trigger_regex):
            raise ValueError("trigger_regex contains nested quantifiers")
        try:
            _compile_trigger(trigger_regex)
        except regex.error as exc:
            raise ValueError("trigger_regex is invalid") from exc

    def get_injection_data(
        self, session_id: str, user_message: str = ""
    ) -> dict[str, Any]:
        universal = copy.deepcopy(self.universal.get(session_id, []))
        contextual = copy.deepcopy(self.contextual.get(session_id, []))
        hit_contents = []
        specific = self.specific.get(session_id, [])
        if (
            not specific
            or not user_message
            or len(user_message) > MAX_MATCH_MESSAGE_LENGTH
        ):
            return {
                "universal": universal,
                "contextual": contextual,
                "specific": hit_contents,
            }

        deadline = time.perf_counter() + TOTAL_MATCH_BUDGET_SECONDS
        now = time.time()
        for trait in specific:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                logger.warning("特定表征匹配达到总时间预算，已停止后续匹配。")
                break
            pattern = trait.get("trigger_regex", "")
            if not pattern:
                continue
            try:
                matched = _compile_trigger(pattern).search(
                    user_message,
                    timeout=min(PER_PATTERN_TIMEOUT_SECONDS, remaining),
                )
            except TimeoutError:
                pattern_id = hashlib.sha256(
                    pattern.encode("utf-8")
                ).hexdigest()[:12]
                logger.warning(f"特定表征正则匹配超时: pattern={pattern_id}")
                continue
            except regex.error:
                pattern_id = hashlib.sha256(
                    pattern.encode("utf-8")
                ).hexdigest()[:12]
                logger.warning(f"特定表征正则运行失败: pattern={pattern_id}")
                continue
            if matched is None:
                continue
            hit_contents.append(trait["content"])
            trait["trigger_count"] = trait.get("trigger_count", 0) + 1
            trait["last_seen"] = now

        if hit_contents:
            self._mark_dirty("specific")
        return {
            "universal": universal,
            "contextual": contextual,
            "specific": hit_contents,
        }

    def apply_learning_result(self, session_id: str, payload: Any) -> bool:
        """Validate and apply one LLM result without partial mutations."""
        if not isinstance(payload, dict):
            raise ValueError("learning result must be an object")

        for field in ("universal", "contextual", "specific"):
            if not isinstance(payload.get(field), list):
                raise ValueError(f"{field} must be a list")

        universal_contents = []
        for content in payload["universal"]:
            if not isinstance(content, str) or not content.strip():
                raise ValueError("universal entries must be non-empty strings")
            universal_contents.append(content)

        contextual_items = []
        for item in payload["contextual"]:
            if not isinstance(item, dict):
                raise ValueError("contextual entries must be objects")
            scene = item.get("scene")
            behavior = item.get("behavior")
            if not isinstance(scene, str) or not scene.strip():
                raise ValueError("contextual scene must be a non-empty string")
            if not isinstance(behavior, str) or not behavior.strip():
                raise ValueError("contextual behavior must be a non-empty string")
            contextual_items.append((scene, behavior))

        specific_items = []
        for item in payload["specific"]:
            if not isinstance(item, dict):
                raise ValueError("specific entries must be objects")
            content = item.get("content")
            trigger_regex = item.get("trigger_regex")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("specific content must be a non-empty string")
            self.validate_trigger_regex(trigger_regex)
            specific_items.append((content, trigger_regex))

        now = time.time()
        new_universal = self._build_universal_traits(
            session_id, universal_contents
        )

        new_contextual = copy.deepcopy(self.contextual.get(session_id, []))
        new_contextual.extend(
            {
                "scene": scene,
                "behavior": behavior,
                "created_at": now,
                "_in_buffer": True,
            }
            for scene, behavior in contextual_items
        )
        max_contextual = self.max_contextual_per_session
        if len(new_contextual) > max_contextual:
            new_contextual = new_contextual[-max_contextual:]
        self._set_buffer_markers(new_contextual)

        new_specific = copy.deepcopy(self.specific.get(session_id, []))
        for content, trigger_regex in specific_items:
            existing = next(
                (item for item in new_specific if item.get("content") == content),
                None,
            )
            if existing is not None:
                existing["trigger_regex"] = trigger_regex
                continue
            new_specific.append({
                "content": content,
                "trigger_regex": trigger_regex,
                "trigger_count": 1,
                "first_seen": now,
                "last_seen": now,
            })

        max_specific = self.max_specific_per_session
        if len(new_specific) > max_specific:
            excess = len(new_specific) - max_specific
            new_specific = sorted(
                new_specific, key=lambda item: item.get("trigger_count", 0)
            )[excess:]

        old_values = {
            "universal": self.universal.get(session_id, []),
            "contextual": self.contextual.get(session_id, []),
            "specific": self.specific.get(session_id, []),
        }
        new_values = {
            "universal": new_universal,
            "contextual": new_contextual,
            "specific": new_specific,
        }
        changed_layers = [
            layer
            for layer in new_values
            if new_values[layer] != old_values[layer]
        ]
        if not changed_layers:
            return False

        for layer in changed_layers:
            getattr(self, layer)[session_id] = new_values[layer]
        self._mark_dirty(*changed_layers)
        return True

    async def save_specific(self) -> bool:
        return await self._save_layers({"specific"})

    # ==================== 公共保存逻辑 ====================

    def _mark_dirty(self, *layers: str) -> None:
        """Mark changed layers and ensure one delayed save is active."""
        self._dirty.update(layers)
        if self._save_timer is not None and not self._save_timer.done():
            return
        self._save_timer = asyncio.create_task(self._delayed_save())

    async def _delayed_save(self) -> None:
        try:
            await asyncio.sleep(self._save_delay)
            while self._dirty:
                if not await self._save_layers(set(self._dirty)):
                    break
        finally:
            self._save_timer = None

    def _any_dirty(self) -> bool:
        return bool(self._dirty)

    async def _save_layers(self, requested: set[str]) -> bool:
        async with self._save_lock:
            if not self._recover_save_transaction():
                return False
            layers = [layer for layer in LAYERS if layer in requested & self._dirty]
            if not layers:
                return True
            if len(layers) == 1:
                layer = layers[0]
                try:
                    self._write_json_atomic(
                        self._layer_files[layer], getattr(self, layer)
                    )
                except OSError as exc:
                    logger.error(f"保存 {layer} 失败: {exc}")
                    return False
                self._dirty.discard(layer)
                return True
            return self._save_transaction(layers)

    def _save_transaction(self, layers: list[str]) -> bool:
        transaction_id = time.time_ns()
        entries = []
        try:
            for layer in layers:
                target = self._layer_files[layer]
                temp_name = f"{os.path.basename(target)}.txn.{transaction_id}.tmp"
                temp_path = os.path.join(self.data_dir, temp_name)
                self._write_json_file(temp_path, getattr(self, layer))
                entries.append({
                    "layer": layer,
                    "temp": temp_name,
                    "target": os.path.basename(target),
                    "sha256": self._file_hash(temp_path),
                })
            self._write_json_atomic(
                self.transaction_file, {"version": 1, "entries": entries}
            )
            for entry in entries:
                os.replace(
                    os.path.join(self.data_dir, entry["temp"]),
                    os.path.join(self.data_dir, entry["target"]),
                )
            os.remove(self.transaction_file)
        except OSError as exc:
            logger.error(f"多文件保存失败: {exc}")
            if not os.path.exists(self.transaction_file):
                for entry in entries:
                    temp = os.path.join(self.data_dir, entry["temp"])
                    if os.path.exists(temp):
                        try:
                            os.remove(temp)
                        except OSError:
                            pass
            return False
        self._dirty.difference_update(layers)
        return True

    async def force_save(self) -> bool:
        if self._save_timer is not None and not self._save_timer.done():
            self._save_timer.cancel()
            try:
                await self._save_timer
            except asyncio.CancelledError:
                pass
            self._save_timer = None
        return await self._save_layers(set(self._dirty))

    # ==================== 聊天记录 ====================

    def load_chat_history(self):
        self._load_layer(self.chat_history_file, "chat_history")

    async def save_chat_history(self) -> bool:
        return await self._save_layers({"chat_history"})

    def add_message_to_history(self, session_id: str, message: dict[str, Any]):
        if session_id not in self.chat_history:
            self.chat_history[session_id] = []
        self.chat_history[session_id].append(message)
        excess = len(self.chat_history[session_id]) - MAX_CHAT_HISTORY_PER_SESSION
        if excess > 0:
            del self.chat_history[session_id][:excess]
        self._mark_dirty("chat_history")

    def get_chat_history(
        self, session_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        return self.chat_history.get(session_id, [])[-limit:]

    def get_history_sessions(self) -> list[str]:
        return list(self.chat_history)

    def get_contextual_sessions(self) -> list[str]:
        return list(self.contextual)

    def get_analysis_batch(
        self, session_id: str, limit: int = 100
    ) -> tuple[list[dict[str, Any]], object | None]:
        batch = self.chat_history.get(session_id, [])[-limit:]
        marker = batch[-1] if batch else None
        return batch, marker

    def consume_analysis_batch(self, session_id: str, marker: object | None) -> bool:
        if marker is None:
            return False
        history = self.chat_history.get(session_id, [])
        for index, message in enumerate(history):
            if message is marker:
                del history[: index + 1]
                self._mark_dirty("chat_history")
                return True
        return False

    def clear_chat_history(self, session_id: str):
        if session_id in self.chat_history:
            self.chat_history[session_id] = []
            self._mark_dirty("chat_history")

    # ==================== WebUI 管理 ====================

    def layer_revision(self, session_id: str, layer: str) -> str:
        if layer not in ("universal", "contextual", "specific"):
            raise ValueError(f"unknown layer: {layer}")
        entries = getattr(self, layer).get(session_id, [])
        canonical = json.dumps(
            entries,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def get_snapshot(self) -> dict[str, Any]:
        """返回三层表征的实时快照（供 WebUI 展示）。"""
        sids = set(self.universal) | set(self.contextual) | set(self.specific)
        return {
            "universal": copy.deepcopy(self.universal),
            "contextual": copy.deepcopy(self.contextual),
            "specific": copy.deepcopy(self.specific),
            "revisions": {
                layer: {
                    session_id: self.layer_revision(session_id, layer)
                    for session_id in sids
                }
                for layer in ("universal", "contextual", "specific")
            },
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
            "injection_enabled": self.enable_style_injection,
            "caps": {
                "universal": MAX_UNIVERSAL_PER_SESSION,
                "contextual": self.max_contextual_per_session,
                "specific": self.max_specific_per_session,
            },
        }

    def clear_session(self, session_id: str) -> None:
        """清空某会话的全部三层表征（不改变聊天记录）。"""
        if session_id in self.universal:
            self.universal[session_id] = []
            self._mark_dirty("universal")
        if session_id in self.contextual:
            self.contextual[session_id] = []
            self._mark_dirty("contextual")
        if session_id in self.specific:
            self.specific[session_id] = []
            self._mark_dirty("specific")

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

    @staticmethod
    def _required_field(item: Any, key: str, index: int) -> str:
        if not isinstance(item, dict):
            raise ValueError(f"第 {index + 1} 条格式错误，应为对象")
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"第 {index + 1} 条缺少有效字段 {key}")
        return value.strip()

    def _normalize_layer_replacement(
        self, session_id: str, layer: str, entries: Any
    ) -> list[dict[str, Any]]:
        if layer not in ("universal", "contextual", "specific"):
            raise ValueError(f"未知的表征层: {layer}")
        if not isinstance(entries, list):
            raise ValueError("请求体必须是条目数组")

        now = time.time()
        normalized = []
        seen = set()
        current = getattr(self, layer).get(session_id, [])
        if layer == "universal":
            if len(entries) > MAX_UNIVERSAL_PER_SESSION:
                raise ValueError(
                    f"条目数 {len(entries)} 超过通用表征容量上限 "
                    f"{MAX_UNIVERSAL_PER_SESSION}"
                )
            old = {item["content"]: item for item in current}
            for index, item in enumerate(entries):
                content = self._required_field(item, "content", index)
                if content in seen:
                    raise ValueError(f"第 {index + 1} 条与前面的条目重复")
                seen.add(content)
                previous = old.get(content, {})
                normalized.append({
                    "content": content,
                    "proficiency": previous.get("proficiency", 10),
                    "confirmed_rounds": previous.get("confirmed_rounds", 1),
                    "last_updated": previous.get("last_updated", now),
                })
            return normalized

        if layer == "contextual":
            if len(entries) > self.max_contextual_per_session:
                raise ValueError(
                    f"条目数 {len(entries)} 超过情境表征容量上限 "
                    f"{self.max_contextual_per_session}"
                )
            old = {
                (item["scene"], item["behavior"]): item for item in current
            }
            for index, item in enumerate(entries):
                scene = self._required_field(item, "scene", index)
                behavior = self._required_field(item, "behavior", index)
                key = (scene, behavior)
                if key in seen:
                    raise ValueError(f"第 {index + 1} 条与前面的条目重复")
                seen.add(key)
                previous = old.get(key, {})
                normalized.append({
                    "scene": scene,
                    "behavior": behavior,
                    "created_at": previous.get("created_at", now),
                })
            self._set_buffer_markers(normalized)
            return normalized

        if len(entries) > self.max_specific_per_session:
            raise ValueError(
                f"条目数 {len(entries)} 超过特定表征容量上限 "
                f"{self.max_specific_per_session}"
            )
        old = {item["content"]: item for item in current}
        for index, item in enumerate(entries):
            content = self._required_field(item, "content", index)
            trigger_regex = self._required_field(item, "trigger_regex", index)
            if content in seen:
                raise ValueError(f"第 {index + 1} 条与前面的条目重复")
            seen.add(content)
            self.validate_trigger_regex(trigger_regex)
            previous = old.get(content, {})
            normalized.append({
                "content": content,
                "trigger_regex": trigger_regex,
                "trigger_count": previous.get("trigger_count", 1),
                "first_seen": previous.get("first_seen", now),
                "last_seen": previous.get("last_seen", now),
            })
        return normalized

    async def replace_layer(
        self,
        session_id: str,
        layer: str,
        entries: Any,
        base_revision: str,
    ) -> dict[str, Any]:
        if layer not in ("universal", "contextual", "specific"):
            raise ValueError(f"未知的表征层: {layer}")
        async with self._save_lock:
            if not self._recover_save_transaction():
                raise OSError("存在无法恢复的保存事务")
            if base_revision != self.layer_revision(session_id, layer):
                raise RevisionConflictError("revision_conflict")

            normalized = self._normalize_layer_replacement(
                session_id, layer, entries
            )
            updated_store = copy.deepcopy(getattr(self, layer))
            updated_store[session_id] = normalized
            self._write_json_atomic(self._layer_files[layer], updated_store)
            setattr(self, layer, updated_store)
            self._dirty.discard(layer)
            return {
                "entries": copy.deepcopy(normalized),
                "revision": self.layer_revision(session_id, layer),
            }

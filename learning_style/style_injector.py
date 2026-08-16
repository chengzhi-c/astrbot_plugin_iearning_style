from typing import Any

import re

from astrbot.api import logger

from .style_selector import StyleSelector


class StyleInjector:
    """
    三层表征注入：
    - 通用：全部注入
    - 情境：全部注入（LLM 自行判断场景匹配）
    - 特定：仅注入 trigger_regex 命中用户消息的条目（按需注入，prompt 不膨胀）
    """

    def __init__(self, data_manager, config: dict[str, Any]):
        self.data_manager = data_manager
        self.config = config
        self.style_selector = StyleSelector()

    def should_inject_style(self, session_id: str) -> bool:
        if not self.config.get("enable_style_injection", True):
            return False

        universal = self.data_manager.get_universal_for_session(session_id)
        contextual = self.data_manager.get_contextual_for_session(session_id)
        specific = self.data_manager.get_specific_for_session(session_id)
        return bool(universal) or bool(contextual) or bool(specific)

    def inject_style_to_prompt(
        self, session_id: str, original_system_prompt: str, user_message: str = ""
    ) -> str:
        if not self.should_inject_style(session_id):
            return original_system_prompt

        try:
            style_parts = []

            # 1. 通用表征：全部注入
            universal = self.data_manager.get_universal_for_session(session_id)
            if universal:
                contents = [t["content"] for t in universal]
                style_parts.append(
                    self.style_selector.build_style_text("通用风格", contents)
                )

            # 2. 情境表征：全部注入
            contextual = self.data_manager.get_contextual_for_session(session_id)
            if contextual:
                style_parts.append(
                    self.style_selector.build_contextual_text(contextual)
                )

            # 3. 特定表征：仅注入 trigger_regex 命中用户消息的条目
            specific = self.data_manager.get_specific_for_session(session_id)
            hit = self._match_specific(specific, user_message)
            if hit:
                style_parts.append(
                    self.style_selector.build_style_text("群内流行说法", hit)
                )

            if not style_parts:
                return original_system_prompt

            style_text = "；".join(style_parts)
            full_style_text = f"在回复时，请尽量采用以下风格特点：{style_text}"

            if not original_system_prompt.strip():
                return full_style_text

            new_prompt = f"{original_system_prompt}\n\n{full_style_text}"
            logger.debug(f"为会话 {session_id} 注入风格提示")
            return new_prompt

        except Exception as e:
            logger.error(f"注入风格时发生错误: {e}")
            return original_system_prompt

    @staticmethod
    def _match_specific(specific: list[dict[str, Any]], user_message: str) -> list[str]:
        """返回 trigger_regex 命中用户消息的特定表征 content 列表。

        ReDoS 防护：超长消息（>10000 字符）不匹配，
        避免灾难正则放大；非法正则静默跳过。
        """
        if not specific or not user_message:
            return []
        if len(user_message) > 10000:
            return []
        hit: list[str] = []
        for s in specific:
            pattern = s.get("trigger_regex", "")
            if not pattern:
                continue
            try:
                if re.search(pattern, user_message):
                    hit.append(s["content"])
            except re.error:
                continue
        return hit

    def get_style_summary(self, session_id: str) -> dict[str, Any]:
        universal = self.data_manager.get_universal_for_session(session_id)
        contextual = self.data_manager.get_contextual_for_session(session_id)
        specific = self.data_manager.get_specific_for_session(session_id)

        total = len(universal) + len(contextual) + len(specific)

        if total == 0:
            return {
                "has_styles": False,
                "total_styles": 0,
                "universal_count": 0,
                "contextual_count": 0,
                "specific_count": 0,
                "universal_preview": [],
                "contextual_preview": [],
                "specific_preview": [],
            }

        universal_preview = [t["content"] for t in universal[:3]]
        contextual_preview = [
            f"{t['scene']}→{t['behavior']}" for t in contextual[:3]
        ]
        specific_sorted = sorted(
            specific, key=lambda t: t.get("trigger_count", 0), reverse=True
        )
        specific_preview = [t["content"] for t in specific_sorted[:3]]

        return {
            "has_styles": True,
            "total_styles": total,
            "universal_count": len(universal),
            "contextual_count": len(contextual),
            "specific_count": len(specific),
            "universal_preview": universal_preview,
            "contextual_preview": contextual_preview,
            "specific_preview": specific_preview,
        }

import inspect
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from .learning_style.data_manager import DataManager, StorageRecoveryError
from .learning_style.learning_manager import LearningManager
from .learning_style.scheduler import Scheduler
from .learning_style.style_injector import StyleInjector
from .learning_style.web_ui import StylePage

_LEARN_FAILURE_MESSAGES = {
    "busy": "当前会话正在学习，请稍候。",
    "no_provider": "学习分析失败：未找到可用的 LLM 提供商。",
    "provider_error": "学习分析失败：LLM 提供商调用失败。",
    "invalid_response": "学习分析失败：LLM 返回内容无效。",
}
_RECOVERY_FAILURE_MESSAGE = "风格数据恢复失败，插件已停止读写；请修复保存事务后重启。"


async def _group_name_from_event(event: AstrMessageEvent) -> str:
    """从 AstrBot 消息事件提取平台已提供的群名。"""
    message_obj = getattr(event, "message_obj", None)
    raw_message = getattr(message_obj, "raw_message", None)
    if isinstance(raw_message, dict):
        raw_group_name = raw_message.get("group_name")
    elif hasattr(raw_message, "__dict__"):
        raw_group_name = raw_message.__dict__.get("group_name")
    else:
        raw_group_name = None

    sender = getattr(message_obj, "sender", None)
    group = getattr(message_obj, "group", None)
    for value in (
        raw_group_name,
        getattr(message_obj, "group_name", None),
        getattr(sender, "group_name", None),
        getattr(group, "group_name", None),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()

    get_group_id = getattr(event, "get_group_id", None)
    group_id = get_group_id() if callable(get_group_id) else None
    if not group_id:
        group_id = getattr(message_obj, "group_id", None)
    get_group = getattr(event, "get_group", None)
    if not group_id or not callable(get_group):
        return ""

    try:
        fetched_group = get_group()
        if inspect.isawaitable(fetched_group):
            fetched_group = await fetched_group
    except Exception:
        logger.debug("获取群聊名称失败", exc_info=True)
        return ""

    for value in (
        getattr(fetched_group, "group_name", None),
        getattr(fetched_group, "name", None),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@register(
    "astrbot_plugin_iearning_style",
    "qa296",
    "从聊天中学习他人说话方式。",
    "1.2.0",
    "https://github.com/chengzhi-c/astrbot_plugin_iearning_style",
)
class IearningStylePlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_iearning_style")
        self._storage_error: str | None = None
        self.data_manager = None
        self.learning_manager = None
        self.scheduler = None
        self.style_injector = None
        self.style_page = None

        try:
            self.data_manager = DataManager(plugin_data_dir, self.config)
        except StorageRecoveryError as exc:
            self._storage_error = str(exc)
            logger.error("风格数据恢复失败，插件未启动: %s", exc)
            return
        self.learning_manager = LearningManager(self, self.data_manager, self.config)
        self.scheduler = Scheduler(
            self.data_manager, self.learning_manager, self.config
        )
        self.style_injector = StyleInjector(self.data_manager, self.config)
        self.style_page = StylePage(
            self.context, self.data_manager, self.config, self.learning_manager
        )

    async def initialize(self):
        if getattr(self, "_storage_error", None):
            logger.error("风格插件因数据恢复错误保持未启动状态。")
            return
        self.scheduler.start()
        self.style_page.register()
        logger.info("学习风格插件已加载并启动定时任务。")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if getattr(self, "_storage_error", None):
            return
        if event.get_sender_id() == event.get_self_id():
            return

        session_id = event.unified_msg_origin
        message_content = event.get_message_str()

        if not message_content:
            return

        message = {
            "sender": event.get_sender_name(),
            "content": message_content,
            "timestamp": time.time(),
        }
        group_name = await _group_name_from_event(event)
        if group_name:
            message["session_name"] = group_name

        self.data_manager.add_message_to_history(session_id, message)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req):
        if getattr(self, "_storage_error", None):
            return
        session_id = event.unified_msg_origin

        original_prompt = req.system_prompt or ""
        user_message = event.get_message_str() or ""
        new_prompt = self.style_injector.inject_style_to_prompt(
            session_id, original_prompt, user_message
        )
        req.system_prompt = new_prompt

    @filter.command("风格状态")
    async def style_status(self, event: AstrMessageEvent):
        if getattr(self, "_storage_error", None):
            yield event.plain_result(_RECOVERY_FAILURE_MESSAGE)
            return
        session_id = event.unified_msg_origin
        summary = self.style_injector.get_style_summary(session_id)

        if not summary["has_styles"]:
            yield event.plain_result("当前会话还没有学习到任何风格特点。")
            return

        yield event.plain_result(
            f"当前会话风格状态：\n{StyleInjector.format_summary_block(summary)}"
        )

    @filter.command("清空风格")
    async def clear_styles(self, event: AstrMessageEvent):
        if getattr(self, "_storage_error", None):
            yield event.plain_result(_RECOVERY_FAILURE_MESSAGE)
            return
        session_id = event.unified_msg_origin
        self.data_manager.clear_session(session_id)
        if await self.data_manager.force_save():
            yield event.plain_result("已清空当前会话的所有学习风格。")
        else:
            yield event.plain_result(
                "风格已在内存中清空，但保存失败；系统会自动重试。"
            )

    @filter.command("学习总结")
    async def learn_now(self, event: AstrMessageEvent):
        """手动触发当前会话的学习分析"""
        if getattr(self, "_storage_error", None):
            yield event.plain_result(_RECOVERY_FAILURE_MESSAGE)
            return
        session_id = event.unified_msg_origin

        yield event.plain_result("正在分析聊天记录并学习风格特征，请稍候...")

        try:
            result = await self.learning_manager.analyze_and_learn(session_id)
            if not result.ok:
                if result.code == "insufficient_history":
                    min_history = self.learning_manager.min_history
                    message = (
                        f"当前会话聊天记录不足 {min_history} 条，无法进行分析。"
                    )
                else:
                    message = _LEARN_FAILURE_MESSAGES.get(
                        result.code, "学习分析失败：未知错误。"
                    )
                yield event.plain_result(message)
                return

            if not await self.data_manager.force_save():
                yield event.plain_result(
                    "学习结果已更新，但保存失败；系统会自动重试。"
                )
                return

            summary = self.style_injector.get_style_summary(session_id)
            response = (
                "学习分析完成！\n"
                + StyleInjector.format_summary_block(summary)
            )

            yield event.plain_result(response)

        except Exception:
            logger.exception("手动触发学习分析失败")
            yield event.plain_result("学习分析失败：内部错误。")

    async def terminate(self):
        if getattr(self, "_storage_error", None):
            logger.info("学习风格插件在未启动状态下卸载。")
            return
        await self.scheduler.stop()
        await self.data_manager.force_save(retry_on_failure=False)
        logger.info("学习风格插件已卸载并停止定时任务。")

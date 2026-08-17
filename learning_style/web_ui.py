"""风格管理页面：AstrBot Dashboard 内嵌 Plugin Page。

页面文件位于插件根目录 ``pages/style-manager/index.html``，由 Dashboard
以沙箱 iframe 加载（面板 → 扩展 → 插件详情 → 打开插件页面）。
需要 AstrBot >= 4.26（Plugin Pages 支持）。

Web API（前端经 window.AstrBotPluginPage 桥接调用，路由须以插件名开头）:

    GET  /astrbot_plugin_iearning_style/snapshot
         → {"status": "ok", "data": {universal, contextual, specific}}
    POST /astrbot_plugin_iearning_style/layer
         body {"sid", "layer", "entries"} → {"status": "ok"} / 400
    POST /astrbot_plugin_iearning_style/deduplicate
         body {"sid"} → per-layer removal counts / 500
"""

from typing import Any

from astrbot.api import logger

from .data_manager import DataManager, RevisionConflictError

PLUGIN_NAME = "astrbot_plugin_iearning_style"

_LEARN_ERRORS = {
    "insufficient_history": ("聊天记录不足，无法进行分析", 400),
    "no_provider": ("未找到可用的 LLM 提供商", 503),
    "provider_error": ("LLM 提供商调用失败", 503),
    "invalid_response": ("LLM 返回内容无效", 422),
    "busy": ("当前会话正在学习，请稍候", 409),
}

try:
    from astrbot.api.web import error_response, json_response, request

    _SUPPORTED = True
except ImportError:
    # AstrBot < 4.26 没有 Plugin Pages / astrbot.api.web
    _SUPPORTED = False


class StylePage:
    """注册风格管理页面的后端 API，页面本体由 Dashboard 托管。"""

    def __init__(
        self,
        context: Any,
        data_manager: DataManager,
        config: dict[str, Any],
        learning_manager: Any = None,
    ):
        self.context = context
        self.data_manager = data_manager
        self.config = config
        self.learning_manager = learning_manager
        enabled = config.get("webui_enabled", True)
        if not isinstance(enabled, bool):
            logger.warning("配置 webui_enabled 必须是布尔值，已回退为 True。")
            enabled = True
        self.webui_enabled = enabled

    def register(self) -> None:
        if not self.webui_enabled:
            logger.info("风格管理页面未启用（webui_enabled=false）。")
            return
        if not _SUPPORTED:
            logger.warning(
                "当前 AstrBot 版本不支持插件页面（Plugin Pages），"
                "风格管理页面未注册。请升级 AstrBot 至 v4.26 及以上。"
            )
            return
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/snapshot",
            self._snapshot,
            ["GET"],
            "获取全部会话的三层风格表征快照",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/layer",
            self._save_layer,
            ["POST"],
            "整层替换某会话的风格表征",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/stats",
            self._global_stats,
            ["GET"],
            "获取全局学习统计（总会话/总条目/注入状态/各层容量）",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/learn",
            self._learn_now,
            ["POST"],
            "手动触发某会话的学习分析（等价于聊天命令『学习总结』）",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/deduplicate",
            self._deduplicate_session,
            ["POST"],
            "去除某会话三层表征中的确定性重复项",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/clear",
            self._clear_session,
            ["POST"],
            "清空某会话的全部三层表征（等价于聊天命令『清空风格』）",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/export",
            self._export_session,
            ["POST"],
            "导出某会话的三层表征为 JSON（前端触发下载）",
        )
        logger.info("风格管理页面已注册（面板 → 扩展 → 插件详情 → 打开插件页面）。")

    async def _snapshot(self):
        return json_response(
            {"status": "ok", "data": self.data_manager.get_snapshot()}
        )

    async def _save_layer(self):
        payload = await request.json(default=None)
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象")
        sid = payload.get("sid")
        layer = payload.get("layer")
        if not isinstance(sid, str) or not sid.strip():
            return error_response("缺少会话 ID")
        if layer not in ("universal", "contextual", "specific"):
            return error_response(f"未知的表征层: {layer}")
        base_revision = payload.get("base_revision")
        if not isinstance(base_revision, str) or not base_revision:
            return error_response("缺少基础 revision")
        try:
            result = await self.data_manager.replace_layer(
                sid.strip(),
                layer,
                payload.get("entries"),
                base_revision,
            )
        except RevisionConflictError:
            return error_response(
                "revision_conflict: 服务器数据已更新，请刷新后重新合并",
                status_code=409,
                data={"code": "revision_conflict"},
            )
        except ValueError as e:
            return error_response(str(e))
        except OSError:
            return error_response(
                "保存失败，服务器数据未修改",
                status_code=500,
                data={"code": "save_failed"},
            )
        return json_response({
            "status": "ok",
            "data": {
                "saved": True,
                "entries": result["entries"],
                "revision": result["revision"],
            },
        })

    @staticmethod
    def _sid_of(payload: Any) -> str | None:
        if isinstance(payload, dict):
            sid = payload.get("sid")
            if isinstance(sid, str) and sid.strip():
                return sid.strip()
        return None

    async def _global_stats(self):
        return json_response(
            {"status": "ok", "data": self.data_manager.global_stats()}
        )

    async def _learn_now(self):
        if self.learning_manager is None:
            return error_response(
                "当前后端未提供学习管理器，请到聊天中发送「学习总结」手动触发"
            )
        payload = await request.json(default=None)
        sid = self._sid_of(payload)
        if not sid:
            return error_response("缺少会话 ID")
        try:
            result = await self.learning_manager.analyze_and_learn(sid)
        except Exception:  # noqa: BLE001
            logger.exception("触发学习分析失败")
            return error_response(
                "学习分析发生未知错误",
                status_code=500,
                data={"code": "internal_error"},
            )
        if not result.ok:
            message, status_code = _LEARN_ERRORS[result.code]
            return error_response(
                message,
                status_code=status_code,
                data={"code": result.code},
            )
        if not await self.data_manager.force_save():
            return error_response(
                "学习结果已更新，但保存失败；系统会自动重试",
                status_code=500,
                data={"code": "save_failed"},
            )
        return json_response({
            "status": "ok",
            "data": {"learned": True, "changed": result.changed},
        })

    async def _deduplicate_session(self):
        payload = await request.json(default=None)
        sid = self._sid_of(payload)
        if not sid:
            return error_response("缺少会话 ID")
        try:
            result = await self.data_manager.deduplicate_session(sid)
        except OSError:
            return error_response(
                "去重结果保存失败，服务器数据未修改",
                status_code=500,
                data={"code": "save_failed"},
            )
        return json_response({"status": "ok", "data": result})

    async def _clear_session(self):
        payload = await request.json(default=None)
        sid = self._sid_of(payload)
        if not sid:
            return error_response("缺少会话 ID")
        self.data_manager.clear_session(sid)
        if not await self.data_manager.force_save():
            return error_response(
                "数据已清空，但保存失败；系统会自动重试",
                status_code=500,
                data={"code": "save_failed"},
            )
        return json_response({"status": "ok", "data": {"cleared": True}})

    async def _export_session(self):
        payload = await request.json(default=None)
        sid = self._sid_of(payload)
        if not sid:
            return error_response("缺少会话 ID")
        return json_response(
            {"status": "ok", "data": self.data_manager.export_session(sid)}
        )

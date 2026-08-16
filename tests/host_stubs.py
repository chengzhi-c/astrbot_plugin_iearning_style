"""Minimal AstrBot modules used by unit tests."""

import logging
import sys
from types import ModuleType


def _decorator(*_args, **_kwargs):
    return lambda target: target


class _Filter:
    class EventMessageType:
        ALL = "all"

    command = staticmethod(_decorator)
    event_message_type = staticmethod(_decorator)
    on_llm_request = staticmethod(_decorator)


class _Request:
    async def json(self, default=None):
        return default


def install_astrbot_stubs() -> None:
    if "astrbot.api" in sys.modules:
        return

    astrbot = ModuleType("astrbot")
    api = ModuleType("astrbot.api")
    event = ModuleType("astrbot.api.event")
    star = ModuleType("astrbot.api.star")
    web = ModuleType("astrbot.api.web")
    astrbot.__path__ = []
    api.__path__ = []

    api.logger = logging.getLogger("astrbot-test")

    class Context:
        pass

    class Star:
        def __init__(self, context=None):
            self.context = context

    class StarTools:
        @staticmethod
        def get_data_dir(_plugin_name):
            return "."

    class AstrMessageEvent:
        pass

    star.Context = Context
    star.Star = Star
    star.StarTools = StarTools
    star.register = _decorator
    event.AstrMessageEvent = AstrMessageEvent
    event.filter = _Filter()

    web.request = _Request()
    web.json_response = lambda data=None, **_kwargs: data
    web.error_response = lambda message, **kwargs: {
        "status": "error",
        "message": message,
        "data": kwargs.get("data"),
    }

    astrbot.api = api
    sys.modules.update({
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.event": event,
        "astrbot.api.star": star,
        "astrbot.api.web": web,
    })

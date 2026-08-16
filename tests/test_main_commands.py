"""Chat command behavior tests."""

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from learning_style.learning_manager import LearnResult

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PARENT = PROJECT_ROOT.parent
if str(PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(PROJECT_PARENT))

IearningStylePlugin = importlib.import_module(
    f"{PROJECT_ROOT.name}.main"
).IearningStylePlugin


class FakeEvent:
    unified_msg_origin = "s1"

    @staticmethod
    def plain_result(text):
        return text


class FakeLearningManager:
    def __init__(self, result):
        self.result = result
        self.min_history = 2

    async def analyze_and_learn(self, _session_id):
        return self.result


class RaisingLearningManager:
    min_history = 2

    async def analyze_and_learn(self, _session_id):
        raise RuntimeError("sensitive provider detail")


class FakeDataManager:
    def __init__(self, save_result=True):
        self.save_result = save_result

    async def force_save(self):
        return self.save_result


class FakeInjector:
    @staticmethod
    def get_style_summary(_session_id):
        return {
            "has_styles": True,
            "universal_count": 1,
            "contextual_count": 0,
            "specific_count": 0,
            "universal_preview": ["简短"],
            "contextual_preview": [],
            "specific_preview": [],
        }


def run(coro):
    return asyncio.run(coro)


async def collect_learn_output(result, *, save_result=True):
    plugin = SimpleNamespace(
        learning_manager=FakeLearningManager(result),
        data_manager=FakeDataManager(save_result),
        style_injector=FakeInjector(),
        config={"min_history_for_analysis": 2},
    )
    return [
        item
        async for item in IearningStylePlugin.learn_now(plugin, FakeEvent())
    ]


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("insufficient_history", "当前会话聊天记录不足 2 条，无法进行分析。"),
        ("busy", "当前会话正在学习，请稍候。"),
        ("no_provider", "学习分析失败：未找到可用的 LLM 提供商。"),
        ("provider_error", "学习分析失败：LLM 提供商调用失败。"),
        ("invalid_response", "学习分析失败：LLM 返回内容无效。"),
    ],
)
def test_learn_command_maps_failure_codes(code, expected):
    outputs = run(collect_learn_output(LearnResult(False, code)))
    assert outputs[-1] == expected


def test_learn_command_preserves_success_message():
    outputs = run(
        collect_learn_output(LearnResult(True, "learned", changed=True))
    )
    assert outputs[-1].startswith("学习分析完成！\n")


def test_learn_command_does_not_claim_success_when_save_fails():
    outputs = run(
        collect_learn_output(
            LearnResult(True, "learned", changed=True), save_result=False
        )
    )
    assert outputs[-1] == "学习结果已更新，但保存失败；系统会自动重试。"


def test_learn_command_hides_unexpected_exception_details():
    plugin = SimpleNamespace(
        learning_manager=RaisingLearningManager(),
        data_manager=FakeDataManager(),
        style_injector=FakeInjector(),
        config={"min_history_for_analysis": 2},
    )

    outputs = run(_collect_plugin_output(plugin))

    assert outputs[-1] == "学习分析失败：内部错误。"
    assert "sensitive provider detail" not in outputs[-1]


async def _collect_plugin_output(plugin):
    return [
        item
        async for item in IearningStylePlugin.learn_now(plugin, FakeEvent())
    ]

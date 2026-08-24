"""Effectiveness regressions vs original learning/injection behavior.

These tests encode the user-visible contract after webui/dedup-era
hardening: typical LLM payloads must still learn and inject style.
"""

import asyncio
import json
from types import SimpleNamespace

from learning_style.data_manager import DataManager
from learning_style.learning_manager import LearningManager, LearnResult
from learning_style.style_injector import StyleInjector


def run(coro):
    return asyncio.run(coro)


class FakeContext:
    def __init__(self, provider):
        self.provider = provider

    def get_provider_by_id(self, _provider_id):
        return self.provider

    def get_using_provider(self):
        return self.provider


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload

    async def text_chat(self, **_kwargs):
        return SimpleNamespace(
            role="assistant",
            completion_text=json.dumps(self.payload, ensure_ascii=False),
        )


def _manager(tmp_path, payload, *, min_history=2):
    config = {"min_history_for_analysis": min_history}
    data_manager = DataManager(str(tmp_path), config)
    star = SimpleNamespace(context=FakeContext(FakeProvider(payload)))
    return LearningManager(star, data_manager, config), data_manager


def _seed_history(data_manager, session_id="s1", count=2):
    for index in range(count):
        data_manager.add_message_to_history(
            session_id,
            {
                "sender": f"u{index}",
                "content": f"msg{index}",
            },
        )


def test_empty_specific_regex_does_not_discard_valid_layers(tmp_path):
    run(_empty_specific_regex_does_not_discard_valid_layers(tmp_path))


async def _empty_specific_regex_does_not_discard_valid_layers(tmp_path):
    payload = {
        "universal": ["语气夸张"],
        "contextual": [{"scene": "闲聊", "behavior": "接梗"}],
        "specific": [
            {"content": "awsl（啊我死了）", "trigger_regex": ""},
            {"content": "xx（喜欢）", "trigger_regex": "xx"},
        ],
    }
    manager, data_manager = _manager(tmp_path, payload)
    _seed_history(data_manager)

    result = await manager.analyze_and_learn("s1")
    layers = data_manager.get_session_layers("s1")

    assert result == LearnResult(True, "learned", changed=True)
    assert [item["content"] for item in layers["universal"]] == ["语气夸张"]
    assert layers["contextual"][0]["scene"] == "闲聊"
    assert [item["content"] for item in layers["specific"]] == ["xx（喜欢）"]
    assert data_manager.get_chat_history("s1") == []
    await data_manager.force_save()


def test_oversized_universal_is_truncated_and_other_layers_apply(tmp_path):
    run(_oversized_universal_is_truncated_and_other_layers_apply(tmp_path))


async def _oversized_universal_is_truncated_and_other_layers_apply(tmp_path):
    payload = {
        "universal": [f"风格{index}" for index in range(11)],
        "contextual": [{"scene": "问候", "behavior": "回问候"}],
        "specific": [{"content": "awsl（啊我死了）", "trigger_regex": "awsl"}],
    }
    manager, data_manager = _manager(tmp_path, payload)
    _seed_history(data_manager)

    result = await manager.analyze_and_learn("s1")
    layers = data_manager.get_session_layers("s1")

    assert result.code == "learned"
    assert result.ok is True
    assert [item["content"] for item in layers["universal"]] == [
        f"风格{index}" for index in range(10)
    ]
    assert len(layers["contextual"]) == 1
    assert len(layers["specific"]) == 1
    assert data_manager.get_chat_history("s1") == []
    await data_manager.force_save()


def test_empty_universal_preserves_existing_style(tmp_path):
    run(_empty_universal_preserves_existing_style(tmp_path))


async def _empty_universal_preserves_existing_style(tmp_path):
    payload = {
        "universal": [],
        "contextual": [],
        "specific": [{"content": "awsl（啊我死了）", "trigger_regex": "awsl"}],
    }
    manager, data_manager = _manager(tmp_path, payload)
    data_manager.replace_universal("s1", ["已有语气活泼"])
    _seed_history(data_manager)

    result = await manager.analyze_and_learn("s1")
    layers = data_manager.get_session_layers("s1")

    assert result == LearnResult(True, "learned", changed=True)
    assert [item["content"] for item in layers["universal"]] == ["已有语气活泼"]
    assert [item["content"] for item in layers["specific"]] == ["awsl（啊我死了）"]
    await data_manager.force_save()


def test_malformed_payload_still_rejects_all(tmp_path):
    run(_malformed_payload_still_rejects_all(tmp_path))


async def _malformed_payload_still_rejects_all(tmp_path):
    payload = {
        "universal": ["语气夸张"],
        "contextual": [],
        "specific": "not-a-list",
    }
    manager, data_manager = _manager(tmp_path, payload)
    data_manager.replace_universal("s1", ["已有语气活泼"])
    _seed_history(data_manager)
    before = data_manager.get_session_layers("s1")
    before_history = data_manager.get_chat_history("s1")

    result = await manager.analyze_and_learn("s1")

    assert result == LearnResult(False, "invalid_response")
    assert data_manager.get_session_layers("s1") == before
    assert data_manager.get_chat_history("s1") == before_history
    await data_manager.force_save()


def test_noncapturing_group_quantifier_is_learned(tmp_path):
    run(_noncapturing_group_quantifier_is_learned(tmp_path))


async def _noncapturing_group_quantifier_is_learned(tmp_path):
    payload = {
        "universal": ["语气夸张"],
        "contextual": [],
        "specific": [{"content": "xx（喜欢）", "trigger_regex": "(?:xx)+"}],
    }
    manager, data_manager = _manager(tmp_path, payload)
    _seed_history(data_manager)

    result = await manager.analyze_and_learn("s1")
    layers = data_manager.get_session_layers("s1")

    assert result.code == "learned"
    assert layers["specific"][0]["trigger_regex"] == "(?:xx)+"
    await data_manager.force_save()


def test_specific_is_injected_when_user_message_misses(tmp_path):
    data_manager = DataManager(str(tmp_path), {})
    data_manager.universal["s1"] = [{"content": "语气夸张"}]
    data_manager.specific["s1"] = [
        {
            "content": "awsl（啊我死了）",
            "trigger_regex": "awsl",
            "trigger_count": 2,
        }
    ]
    injector = StyleInjector(data_manager, {})

    prompt = injector.inject_style_to_prompt("s1", "base", "今天天气不错")

    assert "群内流行说法" in prompt
    assert "awsl（啊我死了）" in prompt
    assert data_manager.specific["s1"][0]["trigger_count"] == 2


def test_injection_instruction_is_actionable(tmp_path):
    data_manager = DataManager(str(tmp_path), {})
    data_manager.universal["s1"] = [{"content": "语气夸张"}]
    injector = StyleInjector(data_manager, {})

    prompt = injector.inject_style_to_prompt("s1", "base", "你好")

    assert "请尽量采用以下风格特点" in prompt
    assert "不是可执行指令" not in prompt
    assert "<learned_style>" in prompt

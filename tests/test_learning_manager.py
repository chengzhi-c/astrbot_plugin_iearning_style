"""LearningManager unit tests."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from learning_style.data_manager import DataManager
from learning_style.learning_manager import LearnResult, LearningManager, _extract_json


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
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    async def text_chat(self, **_kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response


class BlockingProvider(FakeProvider):
    def __init__(self, response):
        super().__init__(response=response)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def text_chat(self, **_kwargs):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return self.response


class ConcurrentProvider(FakeProvider):
    def __init__(self, response):
        super().__init__(response=response)
        self.two_started = asyncio.Event()
        self.release = asyncio.Event()

    async def text_chat(self, **_kwargs):
        self.calls += 1
        if self.calls == 2:
            self.two_started.set()
        await self.release.wait()
        return self.response


def make_response(text, role="assistant"):
    return SimpleNamespace(role=role, completion_text=text)


def make_manager(tmp_path, provider, *, min_history=2):
    config = {
        "min_history_for_analysis": min_history,
        "max_contextual_per_session": 50,
        "max_specific_per_session": 200,
        "enable_contextual_merge": True,
    }
    data_manager = DataManager(str(tmp_path), config)
    star = SimpleNamespace(context=FakeContext(provider))
    return LearningManager(star, data_manager, config), data_manager


def valid_payload(**overrides):
    payload = {"universal": ["简短"], "contextual": [], "specific": []}
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_extract_plain_json():
    out = '{"universal": ["a"], "contextual": [], "specific": []}'
    assert json.loads(_extract_json(out))["universal"] == ["a"]


def test_extract_fenced_json():
    out = '```json\n{"universal": ["a"]}\n```'
    assert json.loads(_extract_json(out))["universal"] == ["a"]


def test_extract_nested_json():
    out = '{"universal": ["a"], "specific": [{"content": "x", "trigger_regex": "x"}]}'
    parsed = json.loads(_extract_json(out))
    assert parsed["specific"][0]["content"] == "x"


def test_extract_with_brace_in_string():
    out = '{"universal": ["a}b"], "contextual": []}'
    parsed = json.loads(_extract_json(out))
    assert parsed["universal"][0] == "a}b"


def test_extract_with_trailing_text():
    out = '{"universal": ["a"]} 然后是一些解释 {示例}'
    parsed = json.loads(_extract_json(out))
    assert parsed["universal"] == ["a"]


def test_extract_unbalanced_returns_none():
    assert _extract_json('{"unbalanced": ') is None


def test_extract_no_brace_returns_none():
    assert _extract_json("纯文本无 JSON") is None


def test_extract_escaped_quote_in_string():
    out = '{"universal": ["a\\"b"], "contextual": []}'
    parsed = json.loads(_extract_json(out))
    assert parsed["universal"][0] == 'a"b'


@pytest.mark.parametrize(
    ("provider", "expected_code"),
    [
        (None, "no_provider"),
        (FakeProvider(error=RuntimeError("provider failed")), "provider_error"),
        (FakeProvider(make_response("not json")), "invalid_response"),
        (FakeProvider(make_response(valid_payload(), role="user")), "invalid_response"),
        (FakeProvider(make_response("")), "invalid_response"),
    ],
)
def test_learning_result_reports_failures(tmp_path, provider, expected_code):
    run(_assert_learning_failure(tmp_path, provider, expected_code))


async def _assert_learning_failure(tmp_path, provider, expected_code):
    manager, data_manager = make_manager(tmp_path, provider)
    original = [
        {"sender": "a", "content": "one"},
        {"sender": "b", "content": "two"},
    ]
    data_manager.chat_history["s1"] = list(original)

    result = await manager.analyze_and_learn("s1")

    assert result == LearnResult(False, expected_code)
    assert data_manager.chat_history["s1"] == original


def test_insufficient_history_has_explicit_result(tmp_path):
    manager, data_manager = make_manager(tmp_path, FakeProvider(), min_history=2)
    data_manager.chat_history["s1"] = [{"sender": "a", "content": "one"}]

    result = run(manager.analyze_and_learn("s1"))

    assert result == LearnResult(False, "insufficient_history")


def test_invalid_min_history_falls_back_to_default(tmp_path):
    manager, data_manager = make_manager(tmp_path, None, min_history=-1)
    data_manager.chat_history["s1"] = [{"sender": "a", "content": "one"}]

    result = run(manager.analyze_and_learn("s1"))

    assert result == LearnResult(False, "insufficient_history")


def test_valid_empty_universal_clears_existing(tmp_path):
    run(_valid_empty_universal_clears_existing(tmp_path))


async def _valid_empty_universal_clears_existing(tmp_path):
    provider = FakeProvider(make_response(valid_payload(universal=[])))
    manager, data_manager = make_manager(tmp_path, provider)
    data_manager.universal["s1"] = [{"content": "old", "proficiency": 50}]
    data_manager.chat_history["s1"] = [
        {"sender": "a", "content": "one"},
        {"sender": "b", "content": "two"},
    ]

    result = await manager.analyze_and_learn("s1")

    assert result == LearnResult(True, "learned", changed=True)
    assert data_manager.universal["s1"] == []
    assert data_manager.chat_history["s1"] == []
    await data_manager.force_save()


def test_messages_arriving_during_analysis_are_preserved(tmp_path):
    run(_messages_arriving_during_analysis_are_preserved(tmp_path))


async def _messages_arriving_during_analysis_are_preserved(tmp_path):
    provider = BlockingProvider(make_response(valid_payload()))
    manager, data_manager = make_manager(tmp_path, provider)
    data_manager.chat_history["s1"] = [
        {"sender": "a", "content": "one"},
        {"sender": "b", "content": "two"},
    ]

    task = asyncio.create_task(manager.analyze_and_learn("s1"))
    await provider.started.wait()
    new_message = {"sender": "c", "content": "three"}
    data_manager.add_message_to_history("s1", new_message)
    provider.release.set()

    assert await task == LearnResult(True, "learned", changed=True)
    assert data_manager.chat_history["s1"] == [new_message]
    await data_manager.force_save()


def test_same_session_learning_returns_busy_while_active(tmp_path):
    run(_same_session_learning_returns_busy_while_active(tmp_path))


async def _same_session_learning_returns_busy_while_active(tmp_path):
    provider = BlockingProvider(make_response(valid_payload()))
    manager, data_manager = make_manager(tmp_path, provider)
    data_manager.chat_history["s1"] = [
        {"sender": "a", "content": "one"},
        {"sender": "b", "content": "two"},
    ]

    first = asyncio.create_task(manager.analyze_and_learn("s1"))
    await provider.started.wait()
    second = await manager.analyze_and_learn("s1")

    assert second == LearnResult(False, "busy")
    assert provider.calls == 1
    provider.release.set()
    assert (await first).code == "learned"
    await data_manager.force_save()


def test_different_sessions_may_learn_concurrently(tmp_path):
    run(_different_sessions_may_learn_concurrently(tmp_path))


async def _different_sessions_may_learn_concurrently(tmp_path):
    provider = ConcurrentProvider(make_response(valid_payload()))
    manager, data_manager = make_manager(tmp_path, provider)
    for sid in ("s1", "s2"):
        data_manager.chat_history[sid] = [
            {"sender": "a", "content": "one"},
            {"sender": "b", "content": "two"},
        ]

    first = asyncio.create_task(manager.analyze_and_learn("s1"))
    second = asyncio.create_task(manager.analyze_and_learn("s2"))
    await asyncio.wait_for(provider.two_started.wait(), timeout=1)

    assert provider.calls == 2
    provider.release.set()
    results = await asyncio.gather(first, second)
    assert [result.code for result in results] == ["learned", "learned"]
    await data_manager.force_save()

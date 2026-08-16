"""StylePage API contract tests."""

import asyncio
from types import SimpleNamespace

import pytest

from learning_style.learning_manager import LearnResult
from learning_style.data_manager import DataManager
from learning_style import web_ui


def run(coro):
    return asyncio.run(coro)


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self, default=None):
        return self.payload if self.payload is not None else default


class FakeLearningManager:
    def __init__(self, result):
        self.result = result

    async def analyze_and_learn(self, _session_id):
        return self.result


class FakeDataManager:
    def __init__(self, save_result=True):
        self.save_result = save_result
        self.force_save_calls = 0

    async def force_save(self):
        self.force_save_calls += 1
        return self.save_result


@pytest.fixture(autouse=True)
def response_stubs(monkeypatch):
    monkeypatch.setattr(web_ui, "request", FakeRequest({"sid": "s1"}), raising=False)
    monkeypatch.setattr(
        web_ui,
        "json_response",
        lambda data, **kwargs: {
            "body": data,
            "status_code": kwargs.get("status_code", 200),
        },
        raising=False,
    )
    monkeypatch.setattr(
        web_ui,
        "error_response",
        lambda message, **kwargs: {
            "body": {
                "status": "error",
                "message": message,
                "data": kwargs.get("data"),
            },
            "status_code": kwargs.get("status_code", 400),
        },
        raising=False,
    )


@pytest.mark.parametrize(
    "code",
    [
        "insufficient_history",
        "no_provider",
        "provider_error",
        "invalid_response",
        "busy",
    ],
)
def test_learn_api_maps_failure_codes(code):
    data_manager = FakeDataManager()
    page = web_ui.StylePage(
        SimpleNamespace(),
        data_manager,
        {},
        FakeLearningManager(LearnResult(False, code)),
    )

    response = run(page._learn_now())

    assert response["body"]["status"] == "error"
    assert response["body"]["data"] == {"code": code}
    assert data_manager.force_save_calls == 0


def test_learn_api_reports_success_only_after_save():
    data_manager = FakeDataManager(save_result=True)
    page = web_ui.StylePage(
        SimpleNamespace(),
        data_manager,
        {},
        FakeLearningManager(LearnResult(True, "learned", changed=True)),
    )

    response = run(page._learn_now())

    assert response["body"] == {
        "status": "ok",
        "data": {"learned": True, "changed": True},
    }
    assert data_manager.force_save_calls == 1


def test_learn_api_reports_save_failure():
    data_manager = FakeDataManager(save_result=False)
    page = web_ui.StylePage(
        SimpleNamespace(),
        data_manager,
        {},
        FakeLearningManager(LearnResult(True, "learned", changed=True)),
    )

    response = run(page._learn_now())

    assert response["body"]["status"] == "error"
    assert response["body"]["data"] == {"code": "save_failed"}


@pytest.mark.parametrize("pattern", ["(a+)+$", "a" * 201])
def test_webui_and_learning_share_regex_validation(tmp_path, pattern):
    data_manager = DataManager(str(tmp_path), {})

    with pytest.raises(ValueError):
        web_ui.normalize_webui_entries(
            data_manager,
            "s1",
            "specific",
            [{"content": "bad", "trigger_regex": pattern}],
        )

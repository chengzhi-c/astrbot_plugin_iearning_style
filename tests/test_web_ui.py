"""StylePage API contract tests."""

import asyncio
from types import SimpleNamespace

import pytest

from learning_style import web_ui
from learning_style.data_manager import DataManager
from learning_style.learning_manager import LearnResult


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


class RegisteringContext:
    def __init__(self):
        self.routes = []

    def register_web_api(self, path, handler, methods, description):
        self.routes.append((path, handler, methods, description))


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
    base_revision = data_manager.layer_revision("s1", "specific")
    web_ui.request = FakeRequest({
        "sid": "s1",
        "layer": "specific",
        "entries": [{"content": "bad", "trigger_regex": pattern}],
        "base_revision": base_revision,
    })
    page = web_ui.StylePage(SimpleNamespace(), data_manager, {})

    response = run(page._save_layer())

    assert response["body"]["status"] == "error"


def test_layer_api_returns_entries_and_revision(tmp_path):
    data_manager = DataManager(str(tmp_path), {})
    base_revision = data_manager.layer_revision("s1", "universal")
    web_ui.request = FakeRequest({
        "sid": "s1",
        "layer": "universal",
        "entries": [{"content": "style"}],
        "base_revision": base_revision,
    })
    page = web_ui.StylePage(SimpleNamespace(), data_manager, {})

    response = run(page._save_layer())

    assert response["body"]["status"] == "ok"
    assert response["body"]["data"]["entries"][0]["content"] == "style"
    assert response["body"]["data"]["revision"] != base_revision


def test_layer_api_maps_revision_conflict(tmp_path):
    data_manager = DataManager(str(tmp_path), {})
    stale_revision = data_manager.layer_revision("s1", "universal")
    data_manager.universal["s1"] = [{"content": "server"}]
    web_ui.request = FakeRequest({
        "sid": "s1",
        "layer": "universal",
        "entries": [{"content": "stale"}],
        "base_revision": stale_revision,
    })
    page = web_ui.StylePage(SimpleNamespace(), data_manager, {})

    response = run(page._save_layer())

    assert response["status_code"] == 409
    assert response["body"]["data"] == {"code": "revision_conflict"}
    assert data_manager.universal["s1"][0]["content"] == "server"


def test_registers_six_public_routes():
    context = RegisteringContext()
    page = web_ui.StylePage(context, FakeDataManager(), {"webui_enabled": True})

    page.register()

    assert [(path, methods) for path, _, methods, _ in context.routes] == [
        (f"/{web_ui.PLUGIN_NAME}/snapshot", ["GET"]),
        (f"/{web_ui.PLUGIN_NAME}/layer", ["POST"]),
        (f"/{web_ui.PLUGIN_NAME}/stats", ["GET"]),
        (f"/{web_ui.PLUGIN_NAME}/learn", ["POST"]),
        (f"/{web_ui.PLUGIN_NAME}/clear", ["POST"]),
        (f"/{web_ui.PLUGIN_NAME}/export", ["POST"]),
    ]


def test_disabled_webui_registers_no_routes():
    context = RegisteringContext()
    page = web_ui.StylePage(context, FakeDataManager(), {"webui_enabled": False})
    page.register()
    assert context.routes == []


def test_snapshot_stats_and_export_contracts(tmp_path):
    data_manager = DataManager(str(tmp_path), {})
    data_manager.universal["s1"] = [{"content": "style"}]
    page = web_ui.StylePage(SimpleNamespace(), data_manager, {})

    snapshot = run(page._snapshot())["body"]
    stats = run(page._global_stats())["body"]
    web_ui.request = FakeRequest({"sid": "s1"})
    exported = run(page._export_session())["body"]

    assert snapshot["status"] == "ok"
    assert snapshot["data"]["revisions"]["universal"]["s1"]
    assert stats["data"]["total_sessions"] == 1
    assert exported["data"]["sid"] == "s1"
    assert exported["data"]["universal"][0]["content"] == "style"


def test_clear_api_is_durable(tmp_path):
    data_manager = DataManager(str(tmp_path), {})
    run(_seed_styles(data_manager))
    page = web_ui.StylePage(SimpleNamespace(), data_manager, {})
    web_ui.request = FakeRequest({"sid": "s1"})

    response = run(page._clear_session())

    assert response["body"] == {
        "status": "ok",
        "data": {"cleared": True},
    }
    reloaded = DataManager(str(tmp_path), {})
    assert reloaded.universal["s1"] == []
    assert reloaded.contextual["s1"] == []
    assert reloaded.specific["s1"] == []


async def _seed_styles(data_manager):
    data_manager.replace_universal("s1", ["style"])
    data_manager.add_contextual("s1", "scene", "behavior")
    data_manager.add_or_update_specific("s1", "meme", "meme")
    await data_manager.force_save()


def test_learn_api_requires_manager():
    page = web_ui.StylePage(SimpleNamespace(), FakeDataManager(), {})
    response = run(page._learn_now())
    assert response["body"]["status"] == "error"


def test_clear_api_reports_save_failure():
    data_manager = SimpleNamespace(
        clear_session=lambda _sid: None,
        force_save=_async_false,
    )
    page = web_ui.StylePage(SimpleNamespace(), data_manager, {})
    web_ui.request = FakeRequest({"sid": "s1"})

    response = run(page._clear_session())

    assert response["status_code"] == 500
    assert response["body"]["data"] == {"code": "save_failed"}


async def _async_false():
    return False


def test_layer_api_rejects_missing_revision(tmp_path):
    data_manager = DataManager(str(tmp_path), {})
    page = web_ui.StylePage(SimpleNamespace(), data_manager, {})
    web_ui.request = FakeRequest({
        "sid": "s1",
        "layer": "universal",
        "entries": [],
    })

    response = run(page._save_layer())

    assert response["body"]["status"] == "error"
    assert "revision" in response["body"]["message"]

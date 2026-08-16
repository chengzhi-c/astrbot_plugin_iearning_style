"""Scheduler tests."""

import asyncio
from types import SimpleNamespace

from learning_style.scheduler import Scheduler


def test_invalid_intervals_fall_back_to_defaults():
    scheduler = Scheduler(
        data_manager=object(),
        learning_manager=object(),
        config={
            "analysis_interval_seconds": 0,
            "maintenance_interval_seconds": -1,
        },
    )

    assert scheduler.analysis_interval == 3600
    assert scheduler.maintenance_interval == 86400


def test_perform_analysis_visits_each_session_and_saves():
    asyncio.run(_perform_analysis())


async def _perform_analysis():
    data_manager = SimpleNamespace(
        get_history_sessions=lambda: ["s1", "s2"],
        force_save=_async_result(True),
    )
    learning_manager = SimpleNamespace(
        analyze_and_learn=_result_by_session({
            "s1": SimpleNamespace(ok=True, code="learned"),
            "s2": SimpleNamespace(ok=False, code="busy"),
        })
    )
    scheduler = Scheduler(data_manager, learning_manager, {})

    await scheduler._perform_analysis()

    assert learning_manager.analyze_and_learn.calls == ["s1", "s2"]
    assert data_manager.force_save.calls == 1


def test_perform_analysis_continues_after_session_error():
    asyncio.run(_perform_analysis_with_error())


async def _perform_analysis_with_error():
    data_manager = SimpleNamespace(
        get_history_sessions=lambda: ["bad", "good"],
        force_save=_async_result(False),
    )

    async def analyze(session_id):
        analyze.calls.append(session_id)
        if session_id == "bad":
            raise RuntimeError("provider error")
        return SimpleNamespace(ok=False, code="insufficient_history")

    analyze.calls = []
    scheduler = Scheduler(
        data_manager,
        SimpleNamespace(analyze_and_learn=analyze),
        {},
    )

    await scheduler._perform_analysis()

    assert analyze.calls == ["bad", "good"]
    assert data_manager.force_save.calls == 1


def test_start_and_stop_manage_both_tasks():
    asyncio.run(_start_and_stop())


async def _start_and_stop():
    scheduler = Scheduler(
        SimpleNamespace(
            get_history_sessions=lambda: [],
            get_contextual_sessions=lambda: [],
            force_save=_async_result(True),
        ),
        SimpleNamespace(),
        {"analysis_interval_seconds": 3600, "maintenance_interval_seconds": 3600},
    )
    scheduler.start()
    assert scheduler.is_running is True
    assert scheduler.analysis_task is not None
    assert scheduler.maintenance_task is not None
    await scheduler.stop()
    assert scheduler.is_running is False
    assert scheduler.analysis_task.done()
    assert scheduler.maintenance_task.done()


def test_maintenance_continues_after_merge_error_and_saves():
    asyncio.run(_maintenance_with_error())


async def _maintenance_with_error():
    def merge(session_id):
        merge.calls.append(session_id)
        if session_id == "bad":
            raise RuntimeError("bad data")

    merge.calls = []
    data_manager = SimpleNamespace(
        get_contextual_sessions=lambda: ["bad", "good"],
        merge_contextual_buffer=merge,
        force_save=_async_result(False),
    )
    scheduler = Scheduler(data_manager, SimpleNamespace(), {})

    await scheduler._perform_maintenance()

    assert merge.calls == ["bad", "good"]
    assert data_manager.force_save.calls == 1


def _async_result(value):
    async def call():
        call.calls += 1
        return value

    call.calls = 0
    return call


def _result_by_session(results):
    async def call(session_id):
        call.calls.append(session_id)
        return results[session_id]

    call.calls = []
    return call

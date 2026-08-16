"""DataManager 单元测试。

覆盖三层表征的边界校验、_schedule_save 的 race 修复、
旧格式迁移、以及 ReDoS 防护。

注意：DataManager 的同步写方法（replace_universal/add_contextual/...）
内部调用 asyncio.create_task，必须在事件循环内执行。
本测试用 asyncio.run(...) 包裹此类调用。
"""
import asyncio
import copy
import json
import os
import time

import pytest

from learning_style.data_manager import DataManager, RevisionConflictError


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def dm(tmp_path):
    config = {
        "max_contextual_per_session": 50,
        "max_specific_per_session": 200,
        "enable_contextual_merge": True,
    }
    return DataManager(str(tmp_path), config)


def _new_dm(tmp_path, **overrides):
    config = {
        "max_contextual_per_session": 50,
        "max_specific_per_session": 200,
        "enable_contextual_merge": True,
    }
    config.update(overrides)
    return DataManager(str(tmp_path), config)


# ==================== 通用表征 ====================

def test_replace_universal_marks_dirty(dm):
    run(_replace_universal_seq(dm))
    assert dm.universal["s1"][0]["content"] == "语气活泼"
    assert "universal" in dm._dirty


async def _replace_universal_seq(dm):
    dm.replace_universal("s1", ["语气活泼"])
    await asyncio.sleep(0)  # 让 create_task 入队


def test_replace_universal_preserves_proficiency(dm):
    run(_proficiency_seq(dm))
    traits = {t["content"]: t for t in dm.universal["s1"]}
    assert traits["语气活泼"]["proficiency"] == 15
    assert traits["语气活泼"]["confirmed_rounds"] == 2
    assert traits["爱用短句"]["proficiency"] == 10


async def _proficiency_seq(dm):
    dm.replace_universal("s1", ["语气活泼"])
    await asyncio.sleep(0)
    dm.replace_universal("s1", ["语气活泼", "爱用短句"])
    await asyncio.sleep(0)


# ==================== 情境表征 ====================

def test_add_contextual_fifo_eviction(tmp_path):
    dm = _new_dm(tmp_path, max_contextual_per_session=3)
    run(_fifo_seq(dm))
    assert len(dm.contextual["s1"]) == 3
    scenes = [t["scene"] for t in dm.contextual["s1"]]
    assert scenes == ["场景2", "场景3", "场景4"]


async def _fifo_seq(dm):
    for i in range(5):
        dm.add_contextual("s1", f"场景{i}", f"行为{i}")
        await asyncio.sleep(0)


def test_merge_contextual_buffer_respects_disable_flag(tmp_path):
    dm = _new_dm(tmp_path, enable_contextual_merge=False)
    run(_disable_merge_seq(dm))
    assert len(dm.contextual["s1"]) == 1


async def _disable_merge_seq(dm):
    dm.add_contextual("s1", "场景", "行为")
    await asyncio.sleep(0)
    dm.contextual["s1"][0]["_in_buffer"] = True
    dm.merge_contextual_buffer("s1")


# ==================== 特定表征 + ReDoS 防护 ====================

def test_add_or_update_specific_rejects_bad_regex(dm):
    run(_bad_regex_seq(dm, "("))
    assert "s1" not in dm.specific or len(dm.specific["s1"]) == 0


def test_add_or_update_specific_rejects_long_regex(dm):
    run(_bad_regex_seq(dm, "a" * 201))
    assert "s1" not in dm.specific or len(dm.specific["s1"]) == 0


def test_add_or_update_specific_rejects_nested_quantifier(dm):
    run(_bad_regex_seq(dm, "(a+)+"))
    assert "s1" not in dm.specific or len(dm.specific["s1"]) == 0


async def _bad_regex_seq(dm, regex):
    dm.add_or_update_specific("s1", "梗", regex)
    await asyncio.sleep(0)


def test_add_or_update_specific_increments_trigger_count(dm):
    run(_increment_seq(dm))
    assert dm.specific["s1"][0]["trigger_count"] == 2


async def _increment_seq(dm):
    dm.add_or_update_specific("s1", "梗", "梗")
    await asyncio.sleep(0)
    dm.add_or_update_specific("s1", "梗", "梗")
    await asyncio.sleep(0)


def test_check_specific_capacity_evicts_lowest(tmp_path):
    dm = _new_dm(tmp_path, max_specific_per_session=3)
    run(_capacity_seq(dm))
    assert len(dm.specific["s1"]) == 3
    contents = [t["content"] for t in dm.specific["s1"]]
    assert "梗0" not in contents


async def _capacity_seq(dm):
    for i in range(3):
        dm.add_or_update_specific("s1", f"梗{i}", f"regex{i}")
        await asyncio.sleep(0)
        for _ in range(i):
            dm.add_or_update_specific("s1", f"梗{i}", f"regex{i}")
            await asyncio.sleep(0)
    dm.check_specific_capacity("s1")
    dm.add_or_update_specific("s1", "梗3", "regex3")
    await asyncio.sleep(0)
    dm.check_specific_capacity("s1")


# ==================== replace_layer（服务端归一化并持久化）====================

def test_replace_layer_normalizes_and_persists(dm):
    run(_replace_layer_seq(dm, [{"content": "测试", "proficiency": 50}]))
    assert dm.universal["s1"][0]["content"] == "测试"
    assert dm.universal["s1"][0]["proficiency"] == 10
    assert "universal" not in dm._dirty


async def _replace_layer_seq(dm, entries):
    base_revision = dm.layer_revision("s1", "universal")
    await dm.replace_layer("s1", "universal", entries, base_revision)


# ==================== _schedule_save race 回归 ====================

def test_schedule_save_no_data_loss_under_race(tmp_path):
    """P2 race 回归：连续 mark_dirty 必须最终保存最新值。"""
    dm = _new_dm(tmp_path)
    run(_race_seq(dm))

    dm2 = _new_dm(tmp_path)
    contents = [t["content"] for t in dm2.universal.get("s1", [])]
    assert "b" in contents, f"期待 b 被保存，实际 universal={dm2.universal}"


async def _race_seq(dm):
    dm.replace_universal("s1", ["a"])  # 触发 A
    await asyncio.sleep(0.01)          # A 进入 sleep
    dm.replace_universal("s1", ["b"])  # 触发 B，cancel A
    await dm.force_save()              # 强制同步落盘


def test_force_save_persists_all_layers(tmp_path):
    dm = _new_dm(tmp_path)
    run(_force_save_seq(dm))

    dm2 = _new_dm(tmp_path)
    assert len(dm2.universal["s1"]) == 1
    assert len(dm2.contextual["s1"]) == 1
    assert len(dm2.specific["s1"]) == 1


async def _force_save_seq(dm):
    dm.replace_universal("s1", ["风格"])
    await asyncio.sleep(0)
    dm.add_contextual("s1", "场景", "行为")
    await asyncio.sleep(0)
    dm.add_or_update_specific("s1", "梗", "梗")
    await asyncio.sleep(0)
    await dm.force_save()


# ==================== 旧格式迁移 ====================

def test_handle_old_format_migrates_to_universal(tmp_path):
    old_data = {"s1": [{"content": "语气活泼"}, {"content": "爱用短句"}]}
    with open(os.path.join(str(tmp_path), "styles.json"), "w", encoding="utf-8") as f:
        json.dump(old_data, f)

    dm = _new_dm(tmp_path)
    contents = [t["content"] for t in dm.universal.get("s1", [])]
    assert "语气活泼" in contents
    assert "爱用短句" in contents
    assert "universal" not in dm._dirty
    assert os.path.exists(os.path.join(str(tmp_path), "styles.json.migrated.bak"))
    assert not os.path.exists(os.path.join(str(tmp_path), "styles.json"))
    with open(os.path.join(str(tmp_path), "universal.json"), encoding="utf-8") as f:
        assert "语气活泼" in [item["content"] for item in json.load(f)["s1"]]


def test_handle_old_format_handles_invalid_json(tmp_path):
    with open(os.path.join(str(tmp_path), "styles.json"), "w", encoding="utf-8") as f:
        f.write("{invalid json")

    dm = _new_dm(tmp_path)
    assert os.path.exists(os.path.join(str(tmp_path), "styles.json"))
    assert "s1" not in dm.universal


# ==================== clear_session / export_session / global_stats ====================

def test_clear_session_empties_all_layers(dm):
    run(_clear_seq(dm))
    assert dm.universal["s1"] == []
    assert dm.contextual["s1"] == []
    assert dm.specific["s1"] == []


async def _clear_seq(dm):
    dm.replace_universal("s1", ["风格"])
    await asyncio.sleep(0)
    dm.add_contextual("s1", "场景", "行为")
    await asyncio.sleep(0)
    dm.add_or_update_specific("s1", "梗", "梗")
    await asyncio.sleep(0)
    dm.clear_session("s1")


def test_export_session_strips_in_buffer(dm):
    run(_export_seq(dm))
    exported = dm.export_session("s1")
    for entry in exported["contextual"]:
        assert "_in_buffer" not in entry


async def _export_seq(dm):
    dm.add_contextual("s1", "场景", "行为")
    await asyncio.sleep(0)


def test_global_stats_aggregates_layers(dm):
    run(_stats_seq(dm))
    stats = dm.global_stats()
    assert stats["total_sessions"] == 2
    assert stats["total_entries"] == 2


async def _stats_seq(dm):
    dm.replace_universal("s1", ["风格"])
    await asyncio.sleep(0)
    dm.add_contextual("s2", "场景", "行为")
    await asyncio.sleep(0)


# ==================== P2 判别：保存调度复用 timer，无 cancel 风暴 ====================

def test_schedule_save_reuses_timer(dm):
    """P2 判别：连续 mark_dirty 必须复用同一 timer（V1 会 cancel+重建）。"""
    dm._save_delay = 10  # 拉长延迟避免落盘干扰断言
    run(_reuse_seq(dm))


async def _reuse_seq(dm):
    dm.replace_universal("s1", ["a"])
    await asyncio.sleep(0.02)  # 让调度 task 执行，timer 建立
    t1 = dm._save_timer
    assert t1 is not None
    dm.replace_universal("s1", ["b"])  # 第二次 mark_dirty
    await asyncio.sleep(0.02)
    assert dm._save_timer is t1, "第二次 mark_dirty 必须复用 timer（V1 会重建）"
    await dm.force_save()  # 清理 pending timer


def test_schedule_save_no_recreate(dm, monkeypatch):
    """P2 判别：连续 mark_dirty 只创建一个延迟保存 task（V1 每变更重建）。"""
    dm._save_delay = 10
    created = []
    orig_create = asyncio.create_task

    def spy_create(coro, *a, **kw):
        if getattr(coro, "__qualname__", "") == "DataManager._delayed_save":
            created.append(coro)
        return orig_create(coro, *a, **kw)

    monkeypatch.setattr(asyncio, "create_task", spy_create)
    run(_storm_seq(dm))
    assert len(created) == 1, (
        f"5 次 mark_dirty 只应创建 1 个延迟保存 task，实际 {len(created)}"
    )


async def _storm_seq(dm):
    for i in range(5):
        dm.replace_universal("s1", [f"t{i}"])
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.01)
    await dm.force_save()  # 清理 pending timer


# ==================== P2 护栏：写盘期间变更不丢 / 失败保留 dirty ====================

def test_mark_dirty_during_save_not_lost(tmp_path):
    """护栏：保存完成后再次变更，新值必须落盘（V1/V2 均应通过）。"""
    dm = _new_dm(tmp_path)
    run(_during_save_seq(dm))
    dm2 = _new_dm(tmp_path)
    contents = [t["content"] for t in dm2.universal.get("s1", [])]
    assert contents == ["final"]


async def _during_save_seq(dm):
    dm._save_delay = 0.05
    dm.replace_universal("s1", ["first"])
    await asyncio.sleep(0.08)  # 等第一次延迟保存完成
    dm.replace_universal("s1", ["final"])
    await asyncio.sleep(0.08)  # V2: while 兜底保存；V1: 新 timer 保存
    await dm.force_save()


def test_save_failure_keeps_dirty_and_exits(dm, monkeypatch):
    """护栏：保存失败保留 dirty 且调度不死循环。"""
    dm._save_delay = 0.05
    real_open = open

    def failing_open(*a, **kw):
        if len(a) >= 2 and a[1] == "w":
            raise OSError("disk full")
        return real_open(*a, **kw)

    monkeypatch.setattr("builtins.open", failing_open)
    run(_fail_seq(dm))
    monkeypatch.undo()
    assert "universal" in dm._dirty  # 失败保留 dirty
    assert dm._save_timer is None or dm._save_timer.done()  # 不挂死


async def _fail_seq(dm):
    dm.replace_universal("s1", ["t"])
    await asyncio.sleep(0.25)  # 覆盖多轮迭代窗口；若死循环则此协程无法返回
    await dm.force_save()


# ==================== P1 回归：clear_session 必须延迟落盘 ====================

def test_clear_session_persists(tmp_path):
    """P1 回归：清空后必须调度延迟保存（不等 force_save），重启不回退。"""
    dm = _new_dm(tmp_path)
    run(_clear_persists_seq(dm, os.path.join(str(tmp_path), "universal.json")))


async def _clear_persists_seq(dm, path):
    dm.replace_universal("s1", ["语气活泼"])
    await asyncio.sleep(0)
    await dm.force_save()
    dm._save_delay = 0.1
    dm.clear_session("s1")
    # 轮询磁盘状态（避免裸 sleep 的 flaky 时序），等待延迟保存落盘；
    # 读盘可能恰逢写文件截断窗口，捕获 JSONDecodeError 跳过重试
    for _ in range(40):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            await asyncio.sleep(0.05)
            continue
        if data == {"s1": []}:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("clear_session 后数据未在延迟保存窗口内落盘")


# ==================== P9 回归：chat_history 容量上限 ====================

def test_chat_history_capacity_keeps_recent(dm):
    """P9 回归：超过容量上限时按 FIFO 保留最近 500 条。"""
    run(_history_capacity_seq(dm))
    assert len(dm.chat_history["s1"]) == 500
    assert dm.chat_history["s1"][0]["seq"] == 10
    assert dm.chat_history["s1"][-1]["seq"] == 509


async def _history_capacity_seq(dm):
    for i in range(510):
        dm.add_message_to_history("s1", {"seq": i})


def test_apply_learning_result_is_transactional(dm):
    dm.universal["s1"] = [{"content": "old", "proficiency": 20}]
    dm.contextual["s1"] = [{"scene": "old", "behavior": "old"}]
    dm.specific["s1"] = [{"content": "old", "trigger_regex": "old"}]
    before = copy.deepcopy((dm.universal, dm.contextual, dm.specific))
    payload = {
        "universal": ["new"],
        "contextual": [
            {"scene": "valid", "behavior": "valid"},
            {"scene": "missing behavior"},
        ],
        "specific": [],
    }

    with pytest.raises(ValueError):
        dm.apply_learning_result("s1", payload)

    assert (dm.universal, dm.contextual, dm.specific) == before


def test_apply_learning_result_updates_regex_without_resetting_stats(dm):
    dm.specific["s1"] = [{
        "content": "梗",
        "trigger_regex": "old",
        "trigger_count": 9,
        "first_seen": 10,
        "last_seen": 20,
    }]
    payload = {
        "universal": [],
        "contextual": [],
        "specific": [{"content": "梗", "trigger_regex": "new"}],
    }

    run(_apply_learning_result(dm, payload))

    trait = dm.specific["s1"][0]
    assert trait["trigger_regex"] == "new"
    assert trait["trigger_count"] == 9
    assert trait["first_seen"] == 10
    assert trait["last_seen"] == 20


async def _apply_learning_result(dm, payload):
    assert dm.apply_learning_result("s1", payload) is True
    await asyncio.sleep(0)
    await dm.force_save()


def test_analysis_batch_consumes_only_through_marker(dm):
    first = {"seq": 1}
    marker = {"seq": 2}
    later = {"seq": 3}
    dm.chat_history["s1"] = [first, marker]

    batch, opaque_marker = dm.get_analysis_batch("s1", limit=100)
    assert batch == [first, marker]
    dm.chat_history["s1"].append(later)
    run(_consume_analysis_batch(dm, opaque_marker))

    assert dm.chat_history["s1"] == [later]


def test_analysis_batch_missing_marker_does_not_consume(dm):
    dm.chat_history["s1"] = [{"seq": 1}, {"seq": 2}]
    _, opaque_marker = dm.get_analysis_batch("s1", limit=100)
    replacement = [{"seq": 3}]
    dm.chat_history["s1"] = replacement

    run(_consume_analysis_batch(dm, opaque_marker))

    assert dm.chat_history["s1"] is replacement


async def _consume_analysis_batch(dm, marker):
    dm.consume_analysis_batch("s1", marker)
    await asyncio.sleep(0)
    await dm.force_save()


def test_atomic_save_failure_keeps_previous_json(tmp_path, monkeypatch):
    dm = _new_dm(tmp_path)
    run(_seed_then_fail_atomic_save(dm, monkeypatch))

    with open(dm.universal_file, encoding="utf-8") as f:
        persisted = json.load(f)
    assert [item["content"] for item in persisted["s1"]] == ["old"]
    assert "universal" in dm._dirty
    assert not os.path.exists(dm.universal_file + ".tmp")


async def _seed_then_fail_atomic_save(dm, monkeypatch):
    dm.replace_universal("s1", ["old"])
    await dm.force_save()
    dm.replace_universal("s1", ["new"])

    real_replace = os.replace

    def fail_target_replace(source, target):
        if os.fspath(target) == dm.universal_file:
            raise OSError("interrupted replace")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_target_replace)
    assert await dm.force_save() is False


def test_migration_write_failure_keeps_source(tmp_path, monkeypatch):
    old_file = tmp_path / "styles.json"
    old_file.write_text('{"s1": ["style"]}', encoding="utf-8")

    def fail_write(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(DataManager, "_write_json_atomic", fail_write)
    dm = _new_dm(tmp_path)

    assert old_file.exists()
    assert not (tmp_path / "styles.json.migrated.bak").exists()
    assert "s1" not in dm.universal


def test_wrong_root_shape_is_backed_up_and_not_loaded(tmp_path):
    path = tmp_path / "universal.json"
    path.write_text('[{"content": "bad root"}]', encoding="utf-8")

    dm = _new_dm(tmp_path)

    assert dm.universal == {}
    assert not path.exists()
    assert len(list(tmp_path.glob("universal.json.corrupt.*.bak"))) == 1


def test_invalid_entries_are_backed_up_and_cleaned(tmp_path):
    path = tmp_path / "universal.json"
    path.write_text(
        json.dumps({"s1": [{"content": "valid"}, {"content": 123}]}),
        encoding="utf-8",
    )

    dm = _new_dm(tmp_path)

    assert [item["content"] for item in dm.universal["s1"]] == ["valid"]
    assert len(list(tmp_path.glob("universal.json.corrupt.*.bak"))) == 1
    with path.open(encoding="utf-8") as f:
        cleaned = json.load(f)
    assert [item["content"] for item in cleaned["s1"]] == ["valid"]


def test_valid_tmp_recovers_when_target_is_invalid(tmp_path):
    target = tmp_path / "universal.json"
    target.write_text("{invalid", encoding="utf-8")
    tmp = tmp_path / "universal.json.tmp"
    tmp.write_text(
        json.dumps({"s1": [{"content": "recovered"}]}),
        encoding="utf-8",
    )

    dm = _new_dm(tmp_path)

    assert dm.universal["s1"][0]["content"] == "recovered"
    assert not tmp.exists()


def test_multifile_interruption_rolls_forward_on_restart(tmp_path, monkeypatch):
    dm = _new_dm(tmp_path)
    run(_interrupt_multifile_save(dm, monkeypatch))
    monkeypatch.undo()

    recovered = _new_dm(tmp_path)
    assert recovered.universal["s1"][0]["content"] == "new universal"
    assert recovered.contextual["s1"][0]["scene"] == "new scene"
    assert not (tmp_path / ".save-transaction.json").exists()


async def _interrupt_multifile_save(dm, monkeypatch):
    dm.replace_universal("s1", ["new universal"])
    dm.add_contextual("s1", "new scene", "new behavior")
    await asyncio.sleep(0)

    real_replace = os.replace
    layer_replaces = 0

    def fail_second_layer(source, target):
        nonlocal layer_replaces
        if os.path.basename(os.fspath(target)) in {
            "universal.json",
            "contextual.json",
        }:
            layer_replaces += 1
            if layer_replaces == 2:
                raise OSError("simulated process interruption")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_second_layer)
    assert await dm.force_save() is False
    assert (os.path.exists(dm.universal_file)) != (
        os.path.exists(dm.contextual_file)
    )
    assert os.path.exists(os.path.join(dm.data_dir, ".save-transaction.json"))


@pytest.mark.parametrize("target_layer", ["universal", "specific"])
def test_contextual_merge_marks_every_changed_layer(tmp_path, target_layer):
    dm = _new_dm(tmp_path)
    text = "scene→behavior"
    dm.contextual["s1"] = [{
        "scene": "scene",
        "behavior": "behavior",
        "_in_buffer": True,
    }]
    if target_layer == "universal":
        dm.universal["s1"] = [{"content": text, "proficiency": 10}]
    else:
        dm.specific["s1"] = [{
            "content": text,
            "trigger_regex": "scene",
            "trigger_count": 1,
        }]

    run(_merge_and_save(dm))

    reloaded = _new_dm(tmp_path)
    assert reloaded.contextual["s1"] == []
    if target_layer == "universal":
        assert reloaded.universal["s1"][0]["proficiency"] == 15
    else:
        assert reloaded.specific["s1"][0]["trigger_count"] == 2


async def _merge_and_save(dm):
    dm.merge_contextual_buffer("s1")
    assert "contextual" in dm._dirty
    assert len(dm._dirty) == 2
    assert await dm.force_save() is True


def test_negative_capacities_fall_back_to_defaults(tmp_path):
    dm = _new_dm(
        tmp_path,
        max_contextual_per_session=-1,
        max_specific_per_session=-1,
    )

    run(_add_with_invalid_capacities(dm))

    assert len(dm.contextual["s1"]) == 2
    assert len(dm.specific["s1"]) == 2


async def _add_with_invalid_capacities(dm):
    dm.add_contextual("s1", "one", "one")
    dm.add_contextual("s1", "two", "two")
    dm.add_or_update_specific("s1", "one", "one")
    dm.add_or_update_specific("s1", "two", "two")
    await asyncio.sleep(0)
    await dm.force_save()


def test_regex_timeout_bounds_match_time(tmp_path):
    dm = _new_dm(tmp_path)
    dm.specific["s1"] = [{
        "content": "pathological",
        "trigger_regex": "(a|aa)+$",
        "trigger_count": 1,
        "first_seen": 1,
        "last_seen": 1,
    }]

    started = time.perf_counter()
    injection = dm.get_injection_data("s1", "a" * 5000 + "!")
    elapsed = time.perf_counter() - started

    assert injection["specific"] == []
    assert elapsed < 0.25
    assert dm.specific["s1"][0]["trigger_count"] == 1


def test_specific_hit_updates_stats_and_persists(tmp_path):
    dm = _new_dm(tmp_path)
    dm.specific["s1"] = [{
        "content": "内部梗",
        "trigger_regex": "hello",
        "trigger_count": 4,
        "first_seen": 1,
        "last_seen": 1,
    }]

    run(_hit_and_save(dm))

    reloaded = _new_dm(tmp_path)
    trait = reloaded.specific["s1"][0]
    assert trait["trigger_count"] == 5
    assert trait["last_seen"] > 1


async def _hit_and_save(dm):
    injection = dm.get_injection_data("s1", "well hello there")
    assert injection["specific"] == ["内部梗"]
    assert "specific" in dm._dirty
    assert await dm.force_save() is True


def test_oversized_message_skips_specific_matching(tmp_path):
    dm = _new_dm(tmp_path)
    dm.specific["s1"] = [{
        "content": "梗",
        "trigger_regex": "x",
        "trigger_count": 1,
    }]

    injection = dm.get_injection_data("s1", "x" * 10001)

    assert injection["specific"] == []
    assert dm.specific["s1"][0]["trigger_count"] == 1


def test_layer_revision_rejects_stale_save_without_mutation(tmp_path):
    dm = _new_dm(tmp_path)
    run(_reject_stale_layer_save(dm))


async def _reject_stale_layer_save(dm):
    dm.replace_universal("s1", ["server version"])
    await dm.force_save()
    stale_revision = dm.layer_revision("s1", "universal")
    dm.replace_universal("s1", ["background update"])
    await dm.force_save()
    before = copy.deepcopy(dm.universal)

    with pytest.raises(RevisionConflictError):
        await dm.replace_layer(
            "s1",
            "universal",
            [{"content": "stale edit"}],
            stale_revision,
        )

    assert dm.universal == before


def test_layer_write_failure_keeps_memory_and_revision(tmp_path, monkeypatch):
    dm = _new_dm(tmp_path)
    dm.universal["s1"] = [{"content": "old", "proficiency": 10}]
    before = copy.deepcopy(dm.universal)
    revision = dm.layer_revision("s1", "universal")

    def fail_write(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(dm, "_write_json_atomic", fail_write)

    with pytest.raises(OSError):
        run(dm.replace_layer(
            "s1", "universal", [{"content": "new"}], revision
        ))

    assert dm.universal == before
    assert dm.layer_revision("s1", "universal") == revision


def test_layer_save_returns_normalized_entries_and_new_revision(tmp_path):
    dm = _new_dm(tmp_path)
    dm.specific["s1"] = [{
        "content": "梗",
        "trigger_regex": "old",
        "trigger_count": 7,
        "first_seen": 1,
        "last_seen": 2,
    }]
    base_revision = dm.layer_revision("s1", "specific")

    result = run(dm.replace_layer(
        "s1",
        "specific",
        [{"content": "梗", "trigger_regex": "new"}],
        base_revision,
    ))

    assert result["entries"][0]["trigger_count"] == 7
    assert result["entries"][0]["trigger_regex"] == "new"
    assert result["revision"] == dm.layer_revision("s1", "specific")
    assert result["revision"] != base_revision


def test_snapshot_returns_copies_and_revisions(tmp_path):
    dm = _new_dm(tmp_path)
    dm.universal["s1"] = [{"content": "style"}]

    snapshot = dm.get_snapshot()
    snapshot["universal"]["s1"][0]["content"] = "mutated"

    assert dm.universal["s1"][0]["content"] == "style"
    assert snapshot["revisions"]["universal"]["s1"] == dm.layer_revision(
        "s1", "universal"
    )


def test_public_read_interfaces_do_not_expose_internal_layers(tmp_path):
    dm = _new_dm(tmp_path)
    dm.universal["s1"] = [{"content": "style"}]
    dm.contextual["s1"] = [{
        "scene": "scene",
        "behavior": "behavior",
        "_in_buffer": True,
    }]
    dm.specific["s1"] = [{"content": "meme", "trigger_regex": "meme"}]

    learning = dm.get_learning_context("s1")
    layers = dm.get_session_layers("s1")
    universal = dm.get_universal_for_session("s1")
    contextual = dm.get_contextual_for_session("s1")
    specific = dm.get_specific_for_session("s1")

    learning["universal"][0]["content"] = "changed"
    learning["contextual_buffer"][0]["scene"] = "changed"
    layers["specific"][0]["content"] = "changed"
    universal.clear()
    contextual.clear()
    specific.clear()

    assert dm.universal["s1"][0]["content"] == "style"
    assert dm.contextual["s1"][0]["scene"] == "scene"
    assert dm.specific["s1"][0]["content"] == "meme"

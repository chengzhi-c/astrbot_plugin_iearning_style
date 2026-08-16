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

import pytest

from learning_style.data_manager import DataManager


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
    assert dm._dirty_universal is True


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

def test_add_contextual_fifo_eviction(dm):
    dm.config["max_contextual_per_session"] = 3
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


def test_check_specific_capacity_evicts_lowest(dm):
    dm.config["max_specific_per_session"] = 3
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


# ==================== replace_layer（已归一化写入）====================

def test_replace_layer_writes_normalized(dm):
    normalized = [{"content": "测试", "proficiency": 50, "confirmed_rounds": 3}]
    run(_replace_layer_seq(dm, normalized))
    assert dm.universal["s1"] == normalized
    assert dm._dirty_universal is True


async def _replace_layer_seq(dm, normalized):
    dm.replace_layer("s1", "universal", normalized)
    await asyncio.sleep(0)


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
    assert dm._dirty_universal is True
    assert os.path.exists(os.path.join(str(tmp_path), "styles.json.migrated.bak"))
    assert not os.path.exists(os.path.join(str(tmp_path), "styles.json"))


def test_handle_old_format_handles_invalid_json(tmp_path):
    with open(os.path.join(str(tmp_path), "styles.json"), "w", encoding="utf-8") as f:
        f.write("{invalid json")

    dm = _new_dm(tmp_path)
    assert os.path.exists(os.path.join(str(tmp_path), "styles.json.bak"))
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
    assert dm._dirty_universal is True  # 失败保留 dirty
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
        await dm.add_message_to_history("s1", {"seq": i})


# ==================== S1: transactional learning ====================

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

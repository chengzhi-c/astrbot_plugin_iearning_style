"""StyleInjector 单元测试。

覆盖 format_summary_block 的输出契约（P8 提取后与旧 main.py
两处命令的拼接输出逐字符一致，作为回归护栏）。
"""
from learning_style.style_injector import StyleInjector


def _summary(**overrides):
    base = {
        "has_styles": True,
        "total_styles": 6,
        "universal_count": 3,
        "contextual_count": 2,
        "specific_count": 1,
        "universal_preview": ["A", "B", "C"],
        "contextual_preview": ["X→1", "Y→2"],
        "specific_preview": ["awsl（啊我死了）"],
    }
    base.update(overrides)
    return base


def test_format_block_all_fields():
    s = _summary()
    assert StyleInjector.format_summary_block(s) == (
        "通用表征：3 条\n"
        "情境表征：2 条\n"
        "特定表征：1 条\n"
        "通用 Top-3：A, B, C\n"
        "情境 Top-3：X→1, Y→2\n"
        "特定 Top-3：awsl（啊我死了）"
    )


def test_format_block_no_previews():
    s = _summary(universal_preview=[], contextual_preview=[], specific_preview=[])
    assert StyleInjector.format_summary_block(s) == (
        "通用表征：3 条\n情境表征：2 条\n特定表征：1 条"
    )


def test_format_block_partial_previews():
    s = _summary(universal_preview=["A"], contextual_preview=[], specific_preview=[])
    assert StyleInjector.format_summary_block(s) == (
        "通用表征：3 条\n情境表征：2 条\n特定表征：1 条\n通用 Top-3：A"
    )


def test_format_block_zero_counts():
    s = _summary(
        total_styles=0,
        universal_count=0,
        contextual_count=0,
        specific_count=0,
        universal_preview=[],
        contextual_preview=[],
        specific_preview=[],
    )
    assert StyleInjector.format_summary_block(s) == (
        "通用表征：0 条\n情境表征：0 条\n特定表征：0 条"
    )

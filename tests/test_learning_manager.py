"""LearningManager 单元测试。

聚焦 _extract_json 的括号配平提取，
覆盖围栏、嵌套、字符串内大括号、不配平输入。
"""
import json

import pytest

from learning_style.learning_manager import _extract_json


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

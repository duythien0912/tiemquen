"""toolable.py — schema generation + mock replay assembly path."""

from __future__ import annotations

import pytest

from agents.tiemquen_agent.toolable import (
    ToolableError,
    Toolable,
    function_declaration,
    strip_additional_properties,
)


def add(a: int, b: int, note: str | None = None) -> int:
    """Add two numbers.

    Args:
        a: first addend
        b: second addend
        note: optional note, ignored
    """
    return a + b


def finish(confidence: int, warnings: list[str] | None = None) -> str:
    """Terminal tool.

    Args:
        confidence: 0-100
        warnings: list of warning strings
    """
    return f"done {confidence}"


def test_function_declaration_schema_shape():
    decl = function_declaration(add)
    assert decl["name"] == "add"
    assert decl["description"].startswith("Add two numbers")
    props = decl["parameters"]["properties"]
    assert props["a"] == {"type": "integer", "description": "first addend"}
    assert props["note"]["type"] == "string"
    # required excludes params with defaults (note has default None)
    assert decl["parameters"]["required"] == ["a", "b"]


def test_strip_additional_properties_recursive():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"x": {"type": "object", "additionalProperties": {"type": "string"}}},
    }
    cleaned = strip_additional_properties(schema)
    assert "additionalProperties" not in cleaned
    assert "additionalProperties" not in cleaned["properties"]["x"]


def test_duplicate_tool_names_rejected():
    def add2(a: int, b: int) -> int:  # pragma: no cover - never called
        """dup"""
        return a + b

    add2.__name__ = "add"  # force collision
    with pytest.raises(ToolableError):
        Toolable([add, add2])


def test_replay_mock_mode_shares_dispatch_with_real_calls():
    """MOCK replay must actually CALL the real tool functions (not just log
    names) — that's the whole point of sharing 100% of the assembly path."""
    calls: list[tuple[int, int]] = []

    def record_add(a: int, b: int) -> int:
        """Add and record.

        Args:
            a: x
            b: y
        """
        calls.append((a, b))
        return a + b

    tool = Toolable([record_add, finish])
    result = tool.replay(
        [
            {"name": "record_add", "args": {"a": 2, "b": 3}},
            {"name": "finish", "args": {"confidence": 90}},
        ]
    )
    assert calls == [(2, 3)]  # real function executed, real side effect happened
    assert result["tool_calls"][0] == {"name": "record_add", "args": {"a": 2, "b": 3}, "result": 5}
    assert result["tool_calls"][1]["result"] == "done 90"
    assert result["message"] == ""


def test_replay_bad_args_captured_as_error_not_raised():
    tool = Toolable([add, finish])
    result = tool.replay([{"name": "add", "args": {"a": 1}}])  # missing 'b'
    assert "error" in result["tool_calls"][0]
    assert "bad arguments" in result["tool_calls"][0]["error"]


def test_replay_value_error_captured_as_error():
    def strict(confidence: int) -> str:
        """Strict tool.

        Args:
            confidence: 0-100
        """
        if not 0 <= confidence <= 100:
            raise ValueError("out of range")
        return "ok"

    tool = Toolable([strict])
    result = tool.replay([{"name": "strict", "args": {"confidence": 999}}])
    assert result["tool_calls"][0]["error"] == "strict: out of range"


def test_replay_unknown_tool_captured_as_error():
    tool = Toolable([add])
    result = tool.replay([{"name": "nope", "args": {}}])
    assert "unknown tool" in result["tool_calls"][0]["error"]

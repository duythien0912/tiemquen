"""Function-calling harness (ENGINE-SPEC §3 `toolable.py`, dùng cho §5 import agent).

Toolable pattern: các hàm Python TYPED chính là tool — signature sinh schema
cho model, docstring là spec model-facing. Hai mode:

- REAL: google-genai tool-calling loop (`run(contents)`): gửi prompt (+ image
  parts), model bắt buộc gọi tool (mode ANY), server thu hoạch từng call,
  dừng khi terminal tool (mặc định `finish`) được gọi.
- MOCK: `replay(recorded_calls)` phát lại list tool-call ghi sẵn.

Cả hai đường đều đi qua `_dispatch()` — mock và real chia sẻ 100% code
assembly (tool functions thật được gọi thật, chỉ khác nguồn tool-call).
Trả về: `{"tool_calls": [{"name", "args", "result"|"error"}...], "message": str}`.
"""

from __future__ import annotations

import inspect
import re
import types as _pytypes
import typing
from typing import Any, Callable, Iterable, Sequence

DEFAULT_MODEL = "gemini-flash-latest"

_PY_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


# ------------------------------------------------------------- schema generation


def strip_additional_properties(schema: Any) -> Any:
    """Recursively drop `additionalProperties` keys (Gemini rejects them)."""
    if isinstance(schema, dict):
        return {
            k: strip_additional_properties(v)
            for k, v in schema.items()
            if k != "additionalProperties"
        }
    if isinstance(schema, list):
        return [strip_additional_properties(v) for v in schema]
    return schema


def _annotation_schema(ann: Any) -> dict[str, Any]:
    """Python type hint -> JSON-schema fragment (best effort, string fallback)."""
    origin = typing.get_origin(ann)
    if origin in (typing.Union, _pytypes.UnionType):
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        return _annotation_schema(args[0]) if args else {"type": "string"}
    if origin in (list, tuple, set) or ann in (list, tuple, set):
        item_args = typing.get_args(ann)
        items = _annotation_schema(item_args[0]) if item_args else {"type": "string"}
        return {"type": "array", "items": items}
    if origin is dict or ann is dict:
        return {"type": "object"}
    if isinstance(ann, type) and ann in _PY_TO_JSON:
        return {"type": _PY_TO_JSON[ann]}
    return {"type": "string"}


_ARGS_LINE_RE = re.compile(r"^\s*(\w+)\s*(?:\([^)]*\))?\s*:\s*(.+)$")


def _docstring_param_descs(doc: str) -> dict[str, str]:
    """Parse `Args:`-style lines (`name: mô tả`) into per-param descriptions."""
    descs: dict[str, str] = {}
    in_args = False
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped.lower().rstrip(":") in ("args", "arguments", "tham số"):
            in_args = True
            continue
        if in_args:
            if not stripped:  # blank line ends the Args block
                break
            m = _ARGS_LINE_RE.match(line)
            if m:
                descs[m.group(1)] = m.group(2).strip()
    return descs


def function_declaration(fn: Callable[..., Any]) -> dict[str, Any]:
    """Typed Python function -> Gemini function declaration.

    Docstring = model-facing spec (description). Params with defaults (or
    Optional) are not required. `additionalProperties` is stripped.
    """
    doc = inspect.getdoc(fn) or ""
    sig = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}
    param_descs = _docstring_param_descs(doc)

    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name == "self" or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        prop = _annotation_schema(hints.get(name, param.annotation))
        if name in param_descs:
            prop["description"] = param_descs[name]
        properties[name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(name)

    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return {
        "name": fn.__name__,
        "description": doc,
        "parameters": strip_additional_properties(parameters),
    }


# ---------------------------------------------------------------------- harness


class ToolableError(Exception):
    pass


class Toolable:
    """Tool-calling loop quanh một bộ tool functions (thường là bound methods
    của một assembler stateful, vd `MenuAssembler`)."""

    def __init__(
        self,
        tools: Sequence[Callable[..., Any]],
        model: str = DEFAULT_MODEL,
        max_rounds: int = 16,
        terminal_tool: str | None = "finish",
    ) -> None:
        self.tools: dict[str, Callable[..., Any]] = {fn.__name__: fn for fn in tools}
        if len(self.tools) != len(tools):
            raise ToolableError("duplicate tool names")
        self.model = model
        self.max_rounds = max_rounds
        self.terminal_tool = terminal_tool
        self.declarations = [function_declaration(fn) for fn in tools]

    # ------------------------------------------------------------ shared path

    def _dispatch(
        self, name: str, args: dict[str, Any], harvested: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Execute ONE tool call and harvest it. Both real-mode `run()` and
        mock-mode `replay()` funnel through here — 100% shared assembly."""
        entry: dict[str, Any] = {"name": name, "args": args}
        fn = self.tools.get(name)
        if fn is None:
            entry["error"] = f"unknown tool {name!r}; available: {sorted(self.tools)}"
        else:
            try:
                entry["result"] = fn(**args)
            except TypeError as e:  # bad/missing args — feed back to the model
                entry["error"] = f"bad arguments for {name}: {e}"
            except ValueError as e:
                entry["error"] = f"{name}: {e}"
        harvested.append(entry)
        return entry

    # -------------------------------------------------------------- mock mode

    def replay(
        self, recorded_calls: Iterable[dict[str, Any]], message: str = ""
    ) -> dict[str, Any]:
        """MOCK MODE: phát lại list tool-call ghi sẵn
        (`[{"name": ..., "args": {...}}, ...]`) qua đúng assembly path của
        real mode — tool functions được gọi thật, state được build thật."""
        harvested: list[dict[str, Any]] = []
        for call in recorded_calls:
            self._dispatch(call["name"], dict(call.get("args") or {}), harvested)
        return {"tool_calls": harvested, "message": message}

    # -------------------------------------------------------------- real mode

    def run(self, contents: Sequence[Any]) -> dict[str, Any]:
        """REAL MODE: google-genai loop. `contents` = prompt (+ image parts).

        Model bị ép gọi tool (FunctionCallingConfig mode ANY); mỗi vòng thu
        hoạch các function_call, trả function_response, lặp tới khi terminal
        tool được gọi thành công hoặc hết `max_rounds`.
        """
        from google import genai  # lazy import: real mode only
        from google.genai import types as gtypes

        client = genai.Client()
        config = gtypes.GenerateContentConfig(
            tools=[gtypes.Tool(function_declarations=self.declarations)],
            tool_config=gtypes.ToolConfig(
                function_calling_config=gtypes.FunctionCallingConfig(mode="ANY")
            ),
        )

        harvested: list[dict[str, Any]] = []
        message = ""
        convo: list[Any] = list(contents)
        done = False
        for _round in range(self.max_rounds):
            response = client.models.generate_content(
                model=self.model, contents=convo, config=config
            )
            candidate = response.candidates[0]
            parts = list(getattr(candidate.content, "parts", None) or [])
            calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
            if not calls:
                message = response.text or ""
                break
            convo.append(candidate.content)
            response_parts: list[Any] = []
            for fc in calls:
                entry = self._dispatch(fc.name, dict(fc.args or {}), harvested)
                payload = (
                    {"error": entry["error"]}
                    if "error" in entry
                    else {"result": entry.get("result")}
                )
                response_parts.append(
                    gtypes.Part.from_function_response(name=fc.name, response=payload)
                )
                if fc.name == self.terminal_tool and "error" not in entry:
                    done = True
            convo.append(gtypes.Content(role="user", parts=response_parts))
            if done:
                break
        return {"tool_calls": harvested, "message": message}

"""A2UI v0.9 protocol — builders + parse + validate/REPAIR (ENGINE-SPEC §1).

Một UI payload = list message. Mỗi message: {"version": "v0.9", <đúng 1 action key>}.
Action keys: createSurface · updateComponents · updateDataModel · deleteSurface.

Validator chạy 1 LẦN lúc compose. Triết lý repair:
- lỗi vá được (thiếu version, thiếu action key đoán được theo shape, thiếu
  createSurface, childIds/leaf viết tắt, ref hỏng) -> tự vá + warning;
- lỗi không vá được (không đoán được action, thiếu components, root không tồn
  tại, component ngoài catalog) -> raise A2UIValidationError (real mode bắt
  exception này để retry-1-lần với correction prompt).
Cache chỉ chứa JSON đã sạch — buyer page KHÔNG validate lại.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

VERSION = "v0.9"
ACTION_KEYS = ("createSurface", "updateComponents", "updateDataModel", "deleteSurface")

#: Leaf value shapes per SPEC §1.
LEAF_KEYS = ("path", "literalString", "literalNumber", "literalBoolean")

#: Component keys that are structural, not leaf-value properties.
_STRUCTURAL_KEYS = frozenset({"id", "component", "childId", "childIds", "weight"})

DEFAULT_CATALOG_ID = "tiemquen_emenu_v1"
DEFAULT_SURFACE_ID = "shop_menu"

CATALOGS_DIR = Path(__file__).resolve().parent / "catalogs"


class A2UIValidationError(ValueError):
    """Unrepairable protocol error (real mode: caught -> retry with correction)."""


# --------------------------------------------------------------------- builders


def make_create_surface(surface_id: str, catalog_id: str = DEFAULT_CATALOG_ID) -> dict[str, Any]:
    return {"version": VERSION, "createSurface": {"surfaceId": surface_id, "catalogId": catalog_id}}


def make_update_components(
    surface_id: str, components: list[dict[str, Any]], root: str = "root"
) -> dict[str, Any]:
    return {
        "version": VERSION,
        "updateComponents": {"surfaceId": surface_id, "root": root, "components": components},
    }


def make_update_data_model(surface_id: str, path: str, value: Any) -> dict[str, Any]:
    return {
        "version": VERSION,
        "updateDataModel": {"surfaceId": surface_id, "path": path, "value": value},
    }


def make_delete_surface(surface_id: str) -> dict[str, Any]:
    return {"version": VERSION, "deleteSurface": {"surfaceId": surface_id}}


# ---------------------------------------------------------------------- catalog


def load_catalog(catalog_id: str = DEFAULT_CATALOG_ID) -> dict[str, Any]:
    """Load a component catalog JSON (schema-per-component, SPEC §2)."""
    path = CATALOGS_DIR / f"{catalog_id}.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def catalog_component_names(catalog: dict[str, Any]) -> set[str]:
    return set(catalog.get("components", {}).keys())


# ------------------------------------------------------------------------ parse

_A2UI_TAG_RE = re.compile(r"<a2ui-json>\s*(.*?)\s*</a2ui-json>", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_a2ui(text: str) -> list[dict[str, Any]]:
    """Extract the A2UI message list from raw model output.

    Accepts: <a2ui-json>...</a2ui-json> wrapper (preferred), ```json fences,
    or bare JSON. A single message object is wrapped into a 1-element list.
    """
    candidate = text.strip()
    m = _A2UI_TAG_RE.search(candidate)
    if m:
        candidate = m.group(1)
    else:
        m = _FENCE_RE.search(candidate)
        if m:
            candidate = m.group(1)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as e:
        raise A2UIValidationError(f"output is not valid JSON: {e}") from e
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise A2UIValidationError(f"expected a JSON list of messages, got {type(data).__name__}")
    return data


# --------------------------------------------------------------- validate/repair


def _infer_action_key(payload: dict[str, Any]) -> str | None:
    """Guess the action key from the payload shape (SPEC §1 repair rule)."""
    if "components" in payload:
        return "updateComponents"
    if "catalogId" in payload:
        return "createSurface"
    if "path" in payload and "value" in payload:
        return "updateDataModel"
    return None


def _repair_message(msg: Any, idx: int, warnings: list[str]) -> tuple[str, dict[str, Any]]:
    """Normalize one message to {"version", <action>: payload}. Returns (action, msg)."""
    if not isinstance(msg, dict):
        raise A2UIValidationError(f"message[{idx}] is not an object: {msg!r}")
    msg = dict(msg)

    if msg.get("version") != VERSION:
        if "version" not in msg:
            warnings.append(f"message[{idx}]: missing version -> injected {VERSION!r}")
        else:
            warnings.append(f"message[{idx}]: version {msg['version']!r} -> coerced to {VERSION!r}")
        msg["version"] = VERSION

    actions = [k for k in msg if k in ACTION_KEYS]
    if len(actions) > 1:
        raise A2UIValidationError(f"message[{idx}] has multiple action keys: {actions}")
    if len(actions) == 1:
        action = actions[0]
        if not isinstance(msg[action], dict):
            raise A2UIValidationError(f"message[{idx}].{action} payload is not an object")
        extras = [k for k in msg if k not in (action, "version")]
        if extras:
            warnings.append(f"message[{idx}]: dropped stray keys {extras}")
            msg = {"version": VERSION, action: msg[action]}
        return action, msg

    # No action key — infer from the flattened payload shape.
    payload = {k: v for k, v in msg.items() if k != "version"}
    action = _infer_action_key(payload)
    if action is None:
        raise A2UIValidationError(
            f"message[{idx}]: no action key and shape is not inferable (keys={sorted(payload)})"
        )
    warnings.append(f"message[{idx}]: missing action key -> inferred {action!r} from payload shape")
    return action, {"version": VERSION, action: payload}


def _repair_leaf(comp_id: str, prop: str, value: Any, warnings: list[str]) -> Any | None:
    """Normalize a component property to a leaf-value / event shape.

    Returns the repaired value, or None if the property must be dropped.
    """
    where = f"component {comp_id!r}.{prop}"
    if isinstance(value, dict):
        if "event" in value:
            ev = value["event"]
            if not isinstance(ev, dict) or not isinstance(ev.get("name"), str) or not ev["name"]:
                warnings.append(f"{where}: malformed event (missing name) -> dropped")
                return None
            ctx = ev.get("context", {})
            if not isinstance(ctx, dict):
                warnings.append(f"{where}: event context not an object -> reset to {{}}")
                ctx = {}
            return {"event": {"name": ev["name"], "context": ctx}}
        leaf_keys = [k for k in value if k in LEAF_KEYS]
        if len(leaf_keys) == 1 and len(value) == 1:
            k = leaf_keys[0]
            v = value[k]
            if k == "path" and (not isinstance(v, str) or not v.startswith("/")):
                warnings.append(f"{where}: path {v!r} is not a /pointer -> dropped")
                return None
            return value
        warnings.append(f"{where}: not a valid leaf shape (keys={sorted(value)}) -> dropped")
        return None
    # Raw literals — wrap into the typed leaf shape (repair).
    if isinstance(value, bool):
        warnings.append(f"{where}: raw bool -> wrapped as literalBoolean")
        return {"literalBoolean": value}
    if isinstance(value, (int, float)):
        warnings.append(f"{where}: raw number -> wrapped as literalNumber")
        return {"literalNumber": value}
    if isinstance(value, str):
        if value.startswith("/"):
            warnings.append(f"{where}: raw string {value!r} looks like a pointer -> wrapped as path")
            return {"path": value}
        warnings.append(f"{where}: raw string -> wrapped as literalString")
        return {"literalString": value}
    warnings.append(f"{where}: unsupported value {value!r} -> dropped")
    return None


def _repair_children(comp: dict[str, Any], comp_id: str, warnings: list[str]) -> None:
    """Normalize childId / childIds shapes in place (SPEC §1 flat wire format)."""
    if "childId" in comp and not isinstance(comp["childId"], str):
        warnings.append(f"component {comp_id!r}: childId not a string -> dropped")
        del comp["childId"]
    if "childIds" in comp:
        ch = comp["childIds"]
        if isinstance(ch, list):
            warnings.append(f"component {comp_id!r}: bare childIds list -> wrapped as explicitList")
            comp["childIds"] = {"explicitList": ch}
        elif isinstance(ch, str) and ch.startswith("/"):
            warnings.append(f"component {comp_id!r}: bare childIds pointer -> wrapped as dataBinding")
            comp["childIds"] = {"dataBinding": ch}
        elif not (
            isinstance(ch, dict)
            and (
                (isinstance(ch.get("explicitList"), list) and set(ch) == {"explicitList"})
                or (isinstance(ch.get("dataBinding"), str) and set(ch) == {"dataBinding"})
            )
        ):
            warnings.append(f"component {comp_id!r}: malformed childIds {ch!r} -> dropped")
            del comp["childIds"]


def _validate_components_payload(
    payload: dict[str, Any],
    idx: int,
    warnings: list[str],
    catalog_names: set[str] | None,
) -> dict[str, Any]:
    components = payload.get("components")
    if not isinstance(components, list) or not components:
        raise A2UIValidationError(f"message[{idx}].updateComponents: missing/empty components list")

    root = payload.get("root")
    if not isinstance(root, str) or not root:
        warnings.append(f"message[{idx}]: missing root -> defaulted to 'root'")
        root = "root"

    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for comp in components:
        if not isinstance(comp, dict):
            warnings.append(f"message[{idx}]: non-object component {comp!r} -> dropped")
            continue
        comp = dict(comp)
        comp_id = comp.get("id")
        ctype = comp.get("component")
        if not isinstance(comp_id, str) or not comp_id or not isinstance(ctype, str) or not ctype:
            warnings.append(f"message[{idx}]: component without id/component -> dropped: {comp!r}")
            continue
        if comp_id in seen:
            warnings.append(f"message[{idx}]: duplicate component id {comp_id!r} -> later dropped")
            continue
        if catalog_names is not None and ctype not in catalog_names:
            raise A2UIValidationError(
                f"message[{idx}]: component {comp_id!r} uses type {ctype!r} not in catalog"
            )
        seen.add(comp_id)
        _repair_children(comp, comp_id, warnings)
        for prop in [k for k in comp if k not in _STRUCTURAL_KEYS]:
            repaired = _repair_leaf(comp_id, prop, comp[prop], warnings)
            if repaired is None:
                del comp[prop]
            else:
                comp[prop] = repaired
        clean.append(comp)

    ids = {c["id"] for c in clean}
    if root not in ids:
        raise A2UIValidationError(
            f"message[{idx}]: root {root!r} not found among component ids"
        )

    # Prune dangling explicit refs (bad component refs -> repair + warning).
    for comp in clean:
        if isinstance(comp.get("childId"), str) and comp["childId"] not in ids:
            warnings.append(
                f"component {comp['id']!r}: childId {comp['childId']!r} unknown -> dropped"
            )
            del comp["childId"]
        ch = comp.get("childIds")
        if isinstance(ch, dict) and "explicitList" in ch:
            kept = [c for c in ch["explicitList"] if c in ids]
            dangling = [c for c in ch["explicitList"] if c not in ids]
            if dangling:
                warnings.append(
                    f"component {comp['id']!r}: unknown child refs {dangling} -> pruned"
                )
                ch["explicitList"] = kept

    payload = dict(payload)
    payload["root"] = root
    payload["components"] = clean
    return payload


def validate_and_repair(
    messages: list[dict[str, Any]],
    catalog: dict[str, Any] | None = None,
    default_surface_id: str = DEFAULT_SURFACE_ID,
    default_catalog_id: str = DEFAULT_CATALOG_ID,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate + repair an A2UI message list. Returns (clean_messages, warnings).

    Raises A2UIValidationError on unrepairable input. If `catalog` is given,
    every component type must exist in it.
    """
    if not isinstance(messages, list) or not messages:
        raise A2UIValidationError("payload must be a non-empty list of messages")

    catalog_names = catalog_component_names(catalog) if catalog is not None else None

    clean: list[dict[str, Any]] = []
    warnings: list[str] = []
    surfaces_created: set[str] = set()

    for idx, raw in enumerate(messages):
        action, msg = _repair_message(raw, idx, warnings)
        payload = msg[action]

        surface_id = payload.get("surfaceId")
        if not isinstance(surface_id, str) or not surface_id:
            warnings.append(f"message[{idx}]: missing surfaceId -> defaulted to {default_surface_id!r}")
            surface_id = default_surface_id
            payload = {**payload, "surfaceId": surface_id}
            msg = {"version": VERSION, action: payload}

        if action == "createSurface":
            if not isinstance(payload.get("catalogId"), str) or not payload["catalogId"]:
                warnings.append(f"message[{idx}]: missing catalogId -> defaulted to {default_catalog_id!r}")
                payload = {**payload, "catalogId": default_catalog_id}
                msg = {"version": VERSION, action: payload}
            surfaces_created.add(surface_id)
        elif action in ("updateComponents", "updateDataModel"):
            # ensure_create_surface: auto-prepend a createSurface for unseen surfaces.
            if surface_id not in surfaces_created:
                warnings.append(
                    f"message[{idx}]: surface {surface_id!r} used before createSurface -> auto-prepended"
                )
                clean.insert(0, make_create_surface(surface_id, default_catalog_id))
                surfaces_created.add(surface_id)
            if action == "updateComponents":
                payload = _validate_components_payload(payload, idx, warnings, catalog_names)
                msg = {"version": VERSION, action: payload}
            else:  # updateDataModel
                path = payload.get("path")
                if not isinstance(path, str) or not path.startswith("/"):
                    raise A2UIValidationError(
                        f"message[{idx}].updateDataModel: path must be a /pointer, got {path!r}"
                    )
                if "value" not in payload:
                    raise A2UIValidationError(f"message[{idx}].updateDataModel: missing value")
        # deleteSurface: surfaceId presence already guaranteed above.

        clean.append(msg)

    return clean, warnings

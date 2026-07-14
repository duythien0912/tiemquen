"""Helpers around the chuẩn menu format schema (shared/menu_schema.json)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent / "menu_schema.json"
REPO_ROOT = SCHEMA_PATH.parent.parent
DEMO_FIXTURE_PATH = REPO_ROOT / "data" / "fixtures" / "demo_shop.json"


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_menu(doc: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError if `doc` is not a valid chuẩn menu doc.

    Beyond the JSON Schema, also checks referential integrity:
    every section item must point at an existing dish id.
    """
    jsonschema.validate(instance=doc, schema=load_schema())
    dishes = doc["menu"]["dishes"]
    for section in doc["menu"]["sections"]:
        for dish_id in section["items"]:
            if dish_id not in dishes:
                raise jsonschema.ValidationError(
                    f"section {section['id']!r} references unknown dish {dish_id!r}"
                )


def validation_errors(doc: dict[str, Any]) -> list[str]:
    """Return human-readable errors ([] means valid)."""
    try:
        validate_menu(doc)
    except jsonschema.ValidationError as e:
        return [e.message]
    return []


def load_demo_fixture() -> dict[str, Any]:
    with DEMO_FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

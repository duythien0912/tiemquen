"""Storage adapter (ENGINE-SPEC §10).

Interface: get/put/list/delete per collection. Dev = LocalJSONStorage (file JSON
dưới data/, 1 thư mục / collection). Prod = Firestore adapter cùng interface,
swap-in sau — mọi module chỉ phụ thuộc `Storage`, không phụ thuộc backend.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

_KEY_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class StorageError(Exception):
    pass


class InvalidKeyError(StorageError):
    pass


def _check_name(name: str, kind: str) -> str:
    """Reject keys/collections that could escape the data dir (path traversal)."""
    if not name or not _KEY_RE.match(name) or name in {".", ".."}:
        raise InvalidKeyError(f"invalid {kind}: {name!r}")
    return name


class Storage(ABC):
    """Document store: collection -> key -> JSON-serializable dict."""

    @abstractmethod
    def get(self, collection: str, key: str) -> dict[str, Any] | None:
        """Return the document, or None if absent."""

    @abstractmethod
    def put(self, collection: str, key: str, doc: dict[str, Any]) -> None:
        """Create or overwrite the document."""

    @abstractmethod
    def list(self, collection: str) -> list[str]:
        """Return all keys in the collection (sorted; empty if none)."""

    @abstractmethod
    def delete(self, collection: str, key: str) -> bool:
        """Delete the document. Return True if it existed."""

    # Convenience shared by all backends.
    def exists(self, collection: str, key: str) -> bool:
        return self.get(collection, key) is not None


class LocalJSONStorage(Storage):
    """Dev backend: data/<collection>/<key>.json, atomic writes."""

    def __init__(self, base_dir: str | os.PathLike[str] = "data") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, collection: str, key: str) -> Path:
        _check_name(collection, "collection")
        _check_name(key, "key")
        return self.base_dir / collection / f"{key}.json"

    def get(self, collection: str, key: str) -> dict[str, Any] | None:
        path = self._path(collection, key)
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def put(self, collection: str, key: str, doc: dict[str, Any]) -> None:
        if not isinstance(doc, dict):
            raise StorageError(f"doc must be a dict, got {type(doc).__name__}")
        path = self._path(collection, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file in same dir, then rename.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def list(self, collection: str) -> list[str]:
        _check_name(collection, "collection")
        cdir = self.base_dir / collection
        if not cdir.is_dir():
            return []
        return sorted(p.stem for p in cdir.glob("*.json"))

    def delete(self, collection: str, key: str) -> bool:
        path = self._path(collection, key)
        if not path.is_file():
            return False
        path.unlink()
        return True

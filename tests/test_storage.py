import pytest

from infra.storage import InvalidKeyError, LocalJSONStorage


@pytest.fixture()
def storage(tmp_path):
    return LocalJSONStorage(tmp_path)


def test_get_missing_returns_none(storage):
    assert storage.get("shops", "nope") is None


def test_put_get_roundtrip_preserves_unicode(storage):
    doc = {"name": "Cơm Tấm Cô Ba", "price": 35000}
    storage.put("shops", "s1", doc)
    assert storage.get("shops", "s1") == doc


def test_put_overwrites(storage):
    storage.put("shops", "s1", {"v": 1})
    storage.put("shops", "s1", {"v": 2})
    assert storage.get("shops", "s1") == {"v": 2}


def test_list_sorted_and_scoped_per_collection(storage):
    storage.put("shops", "b", {})
    storage.put("shops", "a", {})
    storage.put("orders", "o1", {})
    assert storage.list("shops") == ["a", "b"]
    assert storage.list("orders") == ["o1"]
    assert storage.list("empty") == []


def test_delete(storage):
    storage.put("shops", "s1", {})
    assert storage.delete("shops", "s1") is True
    assert storage.delete("shops", "s1") is False
    assert storage.get("shops", "s1") is None


def test_exists(storage):
    assert not storage.exists("shops", "s1")
    storage.put("shops", "s1", {})
    assert storage.exists("shops", "s1")


@pytest.mark.parametrize("bad", ["../evil", "a/b", "", ".", "..", "a b"])
def test_path_traversal_keys_rejected(storage, bad):
    with pytest.raises(InvalidKeyError):
        storage.put("shops", bad, {})
    with pytest.raises(InvalidKeyError):
        storage.get(bad, "k")

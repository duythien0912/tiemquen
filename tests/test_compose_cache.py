"""Compose cache: variant files + updateDataModel patch flow (no recompose)."""

import json

import pytest

from compose.cache import CacheError, ComposeCache
from compose.composer import VARIANTS, compose_all_variants
from shared.menu_format import load_demo_fixture


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture()
def cache(tmp_path):
    return ComposeCache(tmp_path / "composed")


@pytest.fixture()
def composed(cache):
    slug = "com-tam-co-ba"
    cache.write_variants(slug, compose_all_variants(load_demo_fixture()))
    return slug


def test_write_and_read_roundtrip(cache, composed):
    assert cache.list_variants(composed) == sorted(VARIANTS)
    for variant in VARIANTS:
        path = cache.variant_path(composed, variant)
        assert path.is_file()
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk == cache.read_variant(composed, variant)
        assert "createSurface" in on_disk[0]


def test_read_missing_variant_returns_none(cache):
    assert cache.read_variant("nope", "table-regular") is None
    assert cache.list_variants("nope") == []


def test_patch_appends_update_data_model_to_every_variant(cache, composed):
    before = {v: len(cache.read_variant(composed, v)) for v in VARIANTS}
    patched = cache.patch_data(composed, "/soldout/dish_suon_nuong", True)
    assert sorted(patched) == sorted(VARIANTS)
    for variant in VARIANTS:
        msgs = cache.read_variant(composed, variant)
        assert len(msgs) == before[variant] + 1  # appended, not recomposed
        tail = msgs[-1]["updateDataModel"]
        assert tail == {
            "surfaceId": "shop_menu",
            "path": "/soldout/dish_suon_nuong",
            "value": True,
        }
        # structure untouched: still exactly one updateComponents message
        assert sum(1 for m in msgs if "updateComponents" in m) == 1


def test_repeated_patch_same_path_replaces_not_grows(cache, composed):
    cache.patch_data(composed, "/prices/dish_tra_da", 4000)
    n = len(cache.read_variant(composed, "table-regular"))
    cache.patch_data(composed, "/prices/dish_tra_da", 5000)
    msgs = cache.read_variant(composed, "table-regular")
    assert len(msgs) == n  # coalesced
    assert msgs[-1]["updateDataModel"]["value"] == 5000


def test_patches_on_different_paths_stack(cache, composed):
    cache.patch_data(composed, "/soldout/dish_tra_da", True)
    cache.patch_data(composed, "/prices/dish_tra_da", 4000)
    msgs = cache.read_variant(composed, "office-lunch")
    paths = [m["updateDataModel"]["path"] for m in msgs if "updateDataModel" in m]
    assert paths[-2:] == ["/soldout/dish_tra_da", "/prices/dish_tra_da"]


def test_patch_bad_path_rejected(cache, composed):
    with pytest.raises(CacheError):
        cache.patch_data(composed, "khong-co-slash", 1)


def test_patch_unknown_shop_is_noop(cache):
    assert cache.patch_data("chua-compose", "/soldout/x", True) == []


def test_delete_shop_clears_variants(cache, composed):
    assert cache.delete_shop(composed) == len(VARIANTS)
    assert cache.list_variants(composed) == []


def test_slug_traversal_rejected(cache):
    with pytest.raises(CacheError):
        cache.variant_path("../evil", "table-regular")
    with pytest.raises(CacheError):
        cache.variant_path("ok", "../../evil")

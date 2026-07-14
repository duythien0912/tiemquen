import pytest

from infra.publish import RESERVED_SLUGS, SlugRegistry, slugify
from infra.storage import LocalJSONStorage


@pytest.fixture()
def registry(tmp_path):
    return SlugRegistry(LocalJSONStorage(tmp_path))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Cơm Tấm Cô Ba", "com-tam-co-ba"),
        ("Bún Đậu Mắm Tôm Đây!!!", "bun-dau-mam-tom-day"),
        ("Phở  Hòa   Pasteur", "pho-hoa-pasteur"),
        ("Trà Sữa 3Q", "tra-sua-3q"),
        ("  Quán Ăn Đêm 24/7  ", "quan-an-dem-24-7"),
    ],
)
def test_slugify_vietnamese(name, expected):
    assert slugify(name) == expected


def test_register_and_resolve(registry):
    slug = registry.register("shop1", "Cơm Tấm Cô Ba")
    assert slug == "com-tam-co-ba"
    assert registry.resolve(slug) == "shop1"
    assert registry.resolve("khong-ton-tai") is None


def test_uniqueness_suffix(registry):
    assert registry.register("shop1", "Cơm Tấm Cô Ba") == "com-tam-co-ba"
    assert registry.register("shop2", "Cơm Tấm Cô Ba") == "com-tam-co-ba-2"
    assert registry.register("shop3", "Cơm Tấm Cô Ba") == "com-tam-co-ba-3"
    assert registry.resolve("com-tam-co-ba-2") == "shop2"


def test_register_is_idempotent_per_shop(registry):
    a = registry.register("shop1", "Cơm Tấm Cô Ba")
    b = registry.register("shop1", "Cơm Tấm Cô Ba")
    assert a == b == "com-tam-co-ba"


def test_reserved_words_get_suffixed(registry):
    assert "api" in RESERVED_SLUGS
    slug = registry.register("shop1", "API")
    assert slug != "api"
    assert registry.resolve(slug) == "shop1"


def test_preferred_slug_wins(registry):
    slug = registry.register("shop1", "Cơm Tấm Cô Ba", preferred_slug="co-ba-q1")
    assert slug == "co-ba-q1"


def test_release(registry):
    slug = registry.register("shop1", "Cơm Tấm Cô Ba")
    assert registry.release(slug) is True
    assert registry.resolve(slug) is None
    # slug freed -> another shop can take the base name
    assert registry.register("shop2", "Cơm Tấm Cô Ba") == "com-tam-co-ba"

"""infra/media.py — image rehost stub: local copy, http download, best-effort."""

from __future__ import annotations

import requests

from infra.media import MediaRehostError, rehost_dish_images, rehost_one


def test_rehost_one_local_file_copy(tmp_path):
    src = tmp_path / "src.png"
    src.write_bytes(b"fake-png-bytes")
    dest_dir = tmp_path / "media" / "shop-a"

    dest = rehost_one(str(src), dest_dir, "dish_com_suon")
    assert dest.is_file()
    assert dest.read_bytes() == b"fake-png-bytes"
    assert dest.name == "dish_com_suon.png"


def test_rehost_one_missing_local_file_raises():
    import pytest

    with pytest.raises(MediaRehostError):
        rehost_one("/no/such/path.png", "unused", "dish_x")  # type: ignore[arg-type]


def test_rehost_one_http_download(tmp_path):
    class FakeResponse:
        content = b"downloaded-bytes"
        headers = {"Content-Type": "image/jpeg"}

        def raise_for_status(self):
            pass

    class FakeSession:
        def get(self, *a, **k):
            return FakeResponse()

    dest = rehost_one(
        "https://cdn.example.com/menu/suon.jpg",
        tmp_path / "media" / "shop-a",
        "dish_suon",
        session=FakeSession(),
    )
    assert dest.read_bytes() == b"downloaded-bytes"
    assert dest.suffix == ".jpg"


def test_rehost_one_http_failure_raises():
    import pytest

    class FailingSession:
        def get(self, *a, **k):
            raise requests.ConnectionError("nope")

    with pytest.raises(MediaRehostError):
        rehost_one(
            "https://cdn.example.com/x.jpg", "unused_dir", "dish_x", session=FailingSession()
        )  # type: ignore[arg-type]


def test_rehost_dish_images_rewrites_menu_doc_in_place(tmp_path):
    src = tmp_path / "raw.png"
    src.write_bytes(b"abc")
    doc = {
        "shop": {"slug": "shop-a"},
        "menu": {
            "dishes": {
                "dish_1": {"name": "Món 1", "price": 30000, "image_url": str(src)},
                "dish_2": {"name": "Món 2", "price": 20000},  # no image -> untouched
            }
        },
    }
    warnings = rehost_dish_images(doc, media_dir=tmp_path / "media")
    assert warnings == []
    assert doc["menu"]["dishes"]["dish_1"]["image_url"] == "/media/shop-a/dish_1.png"
    assert "image_url" not in doc["menu"]["dishes"]["dish_2"]
    assert (tmp_path / "media" / "shop-a" / "dish_1.png").is_file()


def test_rehost_dish_images_best_effort_keeps_original_on_failure(tmp_path):
    doc = {
        "shop": {"slug": "shop-a"},
        "menu": {"dishes": {"dish_1": {"name": "Món 1", "price": 30000, "image_url": "/no/such/file.png"}}},
    }
    warnings = rehost_dish_images(doc, media_dir=tmp_path / "media")
    assert len(warnings) == 1
    assert doc["menu"]["dishes"]["dish_1"]["image_url"] == "/no/such/file.png"  # unchanged


def test_rehost_dish_images_skips_already_rehosted():
    doc = {
        "shop": {"slug": "shop-a"},
        "menu": {"dishes": {"dish_1": {"name": "Món 1", "price": 30000, "image_url": "/media/shop-a/dish_1.png"}}},
    }
    warnings = rehost_dish_images(doc)
    assert warnings == []
    assert doc["menu"]["dishes"]["dish_1"]["image_url"] == "/media/shop-a/dish_1.png"

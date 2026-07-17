"""infra/pdf_export.py — print-ready flyer PDFs per format (mock imagen)."""

import pytest

from infra import pdf_export
from shared.menu_format import load_demo_fixture


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture()
def fixture():
    return load_demo_fixture()


def test_export_flyers_all_formats_creates_real_pdfs(fixture, tmp_path):
    batch_ids = {
        "a5": "office-plaza-1-a5-aaaa",
        "a4": "pantry-a-a4-bbbb",
        "sticker": "tu-lanh-sticker-cccc",
    }
    paths = pdf_export.export_flyers(fixture, batch_ids, media_dir=tmp_path)
    assert set(paths) == set(batch_ids)
    for fmt, path in paths.items():
        assert path == tmp_path / "com-tam-co-ba" / f"flyer_{fmt}_{batch_ids[fmt]}.pdf"
        assert path.is_file()
        data = path.read_bytes()
        assert data[:5] == b"%PDF-"
        assert len(data) > 10_000, f"{fmt}: PDF suspiciously small ({len(data)}B)"


def test_page_size_matches_format_mm(fixture, tmp_path):
    from reportlab.lib.units import mm

    import re

    path = pdf_export.export_flyer(fixture, "a5", "office-x-a5-1234", media_dir=tmp_path)
    text = path.read_bytes().decode("latin-1")
    # /MediaBox [ 0 0 W H ] in points; A5 = 148x210mm print-ready page.
    m = re.search(r"/MediaBox \[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", text)
    assert m, "MediaBox missing"
    w, h = float(m.group(1)), float(m.group(2))
    assert w == pytest.approx(148 * mm, abs=0.5)
    assert h == pytest.approx(210 * mm, abs=0.5)


def test_unknown_format_and_empty_batches_raise(fixture, tmp_path):
    with pytest.raises(pdf_export.PDFExportError):
        pdf_export.export_flyer(fixture, "letter", "b-1", media_dir=tmp_path)
    with pytest.raises(pdf_export.PDFExportError):
        pdf_export.export_flyers(fixture, {}, media_dir=tmp_path)


def test_best_sellers_skips_hidden_and_sold_out(fixture):
    menu = fixture["menu"]
    first_ids = [i for s in menu["sections"] for i in s["items"]][:2]
    menu["dishes"][first_ids[0]]["hidden"] = True
    menu["dishes"][first_ids[1]]["sold_out"] = True
    picks = pdf_export.best_sellers(menu)
    assert len(picks) == 3
    names = {d["name"] for d in picks}
    assert menu["dishes"][first_ids[0]]["name"] not in names
    assert menu["dishes"][first_ids[1]]["name"] not in names


def test_flyer_reuses_cached_hero(fixture, tmp_path):
    from agents.tiemquen_agent import imagen

    hero = imagen.generate_hero(fixture, "a5", media_dir=tmp_path)
    mtime = hero["path"].stat().st_mtime
    pdf_export.export_flyer(fixture, "a5", "b-a5-1", media_dir=tmp_path)
    assert hero["path"].stat().st_mtime == mtime  # not regenerated

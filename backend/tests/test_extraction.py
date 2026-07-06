from pathlib import Path

import pytest

from backend.extraction.classifier import DocKind, classify
from backend.extraction.fast_path import Page
from backend.extraction.segmenter import segment

GOLDEN = Path(__file__).parents[2] / "golden_set" / "docs"


def _read(doc_id: str, filename: str) -> bytes:
    return (GOLDEN / doc_id / filename).read_bytes()


def test_classifier_born_digital_pdf():
    assert classify(_read("gs-0001", "document.pdf"), "document.pdf") == DocKind.born_digital_pdf


def test_classifier_scanned_pdf():
    assert classify(_read("gs-0017", "document.pdf"), "document.pdf") == DocKind.scanned_pdf


def test_classifier_docx_and_text():
    assert classify(_read("gs-0013", "document.docx"), "document.docx") == DocKind.docx
    assert classify(b"plain words", "note.txt") == DocKind.plain_text


def test_classifier_rejects_unknown():
    with pytest.raises(ValueError):
        classify(b"\x00\x01binary", "photo.jpg")


def test_segmenter_finds_sections_with_offsets():
    text = (
        "RESIDENTIAL LEASE AGREEMENT\n\n"
        "1. PARTIES\nThis Lease is between A and B.\n\n"
        "2. TERM\nThe term is 12 months.\n\n"
        "10. GOVERNING LAW\nState of Washington.\n"
    )
    full_text, sections = segment([Page(number=1, text=text)])

    assert [s.section_id for s in sections] == ["sec-0", "sec-1", "sec-2", "sec-10"]
    assert sections[0].heading == "PREAMBLE"
    # offsets slice back to the source text exactly
    term = full_text[sections[2].start : sections[2].end]
    assert term.startswith("2. TERM")
    assert "12 months" in term
    assert sections[3].end == len(full_text)


def test_segmenter_page_provenance():
    pages = [
        Page(number=1, text="1. PARTIES\nOn page one."),
        Page(number=2, text="2. TERM\nOn page two."),
    ]
    _, sections = segment(pages)
    assert [(s.number, s.page) for s in sections] == [("1", 1), ("2", 2)]


def test_segmenter_numbered_list_items_are_not_headings():
    text = "1. PARTIES\nThe parties agree that:\n1. rent is due monthly\n2. pets are allowed\n"
    _, sections = segment([Page(number=1, text=text)])
    assert [s.section_id for s in sections] == ["sec-1"]

from backend.pii.masker import mask_text

KNOWN = [
    ("Jordan Rivera", "PERSON"),
    ("Acme Property Holdings LLC", "ORG"),
    ("4471-3920-0011", "ACCOUNT"),
]


def test_exact_masking_all_occurrences():
    text = "Jordan Rivera signs. Jordan Rivera pays 4471-3920-0011."
    masked, entities = mask_text(text, KNOWN)
    assert "Jordan Rivera" not in masked
    assert "4471-3920-0011" not in masked
    assert masked.count("[PERSON-1]") == 2
    by_value = {e.value: e for e in entities}
    assert by_value["Jordan Rivera"].occurrences == 2
    assert by_value["4471-3920-0011"].placeholder == "[ACCOUNT-1]"


def test_fuzzy_separator_matching_ocr_mutations():
    # OCR-style mutations: doubled spaces, spaced hyphens, stray punctuation
    text = "Signed by Jordan  Rivera; account 4471 - 3920 - 0011; Jordan- Rivera."
    masked, _ = mask_text(text, KNOWN)
    assert "Rivera" not in masked
    assert "3920" not in masked
    assert masked.count("[PERSON-1]") == 2
    assert "[ACCOUNT-1]" in masked


def test_case_insensitive():
    masked, _ = mask_text("JORDAN RIVERA and jordan rivera", KNOWN)
    assert masked == "[PERSON-1] and [PERSON-1]"


def test_longer_entity_wins_over_substring():
    known = [("Acme Property Holdings LLC", "ORG"), ("Acme", "ORG")]
    masked, entities = mask_text("Acme Property Holdings LLC leases.", known)
    assert masked == "[ORG-1] leases."
    assert entities[0].value == "Acme Property Holdings LLC"


def test_no_partial_word_matches():
    known = [("Rivera", "PERSON")]
    masked, _ = mask_text("The Riveranda building.", known)
    assert masked == "The Riveranda building."


def test_unmatched_entities_produce_no_map_rows():
    masked, entities = mask_text("No PII here at all.", KNOWN)
    assert masked == "No PII here at all."
    assert entities == []

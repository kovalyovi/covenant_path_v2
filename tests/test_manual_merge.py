"""
Offline tests for the server-side manual-member merge helpers (db._normalize_name / _same_unit /
_merged_note) — no network, no DB.

The daily sync auto-merges a manually-added person into a real synced member when the NORMALIZED name
matches WITHIN THE SAME UNIT (db.merge_manual_members). These helpers are the Python twins of the web's
logic/manualMembers.ts (normalizeName / sameUnit / mergedNote); this pins the parity so the two surfaces
agree on what "the same person" and "don't lose the notes" mean.

Run: python -m pytest tests/test_manual_merge.py -q
"""

from backend import db


def test_normalize_name_order_insensitive_and_whitespace():
    assert db._normalize_name("Smith, John") == db._normalize_name("John Smith")
    assert db._normalize_name("  John   SMITH ") == "john smith"


def test_normalize_name_strips_apostrophes_and_hyphens():
    # "O'Brien" -> "obrien", "Mary-Jane" -> "maryjane"; order-insensitive.
    assert db._normalize_name("Mary-Jane O'Brien") == db._normalize_name("OBrien Mary-Jane")
    assert db._normalize_name("Mary-Jane O'Brien") == "maryjane obrien"


def test_normalize_name_folds_diacritics():
    # é→e, í→i, ñ→n BEFORE the ASCII filter (which would otherwise delete the letter outright).
    assert db._normalize_name("José García") == db._normalize_name("Jose Garcia")
    assert db._normalize_name("José García") == "garcia jose"


def test_normalize_name_empty():
    assert db._normalize_name("") == ""
    assert db._normalize_name(None) == ""


def test_same_unit_prefers_id_then_name():
    assert db._same_unit("u1", "Alpha", "u1", "Beta") is True          # id wins over differing names
    assert db._same_unit("u1", "Alpha", "u2", "Alpha") is False        # different id
    assert db._same_unit(None, "Alpha Ward", None, "alpha ward") is True   # name fallback, case-insensitive
    assert db._same_unit(None, "Alpha", None, "Beta") is False
    assert db._same_unit(None, "", None, "") is False                  # no way to know → not same


def test_merged_note_never_loses_text_and_is_idempotent():
    assert db._merged_note("existing", "") == "existing"
    assert db._merged_note("", "preserved") == "preserved"
    assert db._merged_note("a", "b") == "a\n\nb"
    assert db._merged_note("a\n\nb", "b") == "a\n\nb"                  # already contains b → unchanged

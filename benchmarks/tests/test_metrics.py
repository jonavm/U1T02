import pytest

from benchmarks.metrics import distance, normalize, score


def test_edit_distance_accounts_for_insertions_deletions_and_substitutions():
    assert distance("kitten", "sitting") == 3
    assert distance("abc", "") == 3
    assert distance("", "abc") == 3
    assert distance(["one", "two"], ["one", "three"]) == 1


def test_normalization_preserves_meaningful_characters():
    assert normalize("  café\n  TEST\t") == "café TEST"
    assert normalize("cafe\u0301") == "café"
    assert score("café", "cafe")["cer"] == pytest.approx(0.25)
    assert score("A", "a")["cer"] == 1


def test_missing_scan_text_is_counted_as_error():
    result = score("hello world", "")
    assert result["cer"] == 1
    assert result["wer"] == 1


def test_insertion_error_rates_are_not_clamped():
    assert score("a", "a b c")["wer"] == 2


def test_whitespace_differences_are_ignored():
    assert score("one\ntwo", "one  two")["cer"] == 0

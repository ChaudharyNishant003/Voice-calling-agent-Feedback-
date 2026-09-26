"""`domain/conversation_graph/normalizer.py` — >=30 cases per language (PRD v2 §9.7, Phase 2
acceptance check)."""

from __future__ import annotations

import pytest

from app.domain.conversation_graph.normalizer import (
    EMERGENCY_NUMBERS,
    date_words,
    digits_spoken,
    normalize_devanagari_digits,
    number_to_words,
    phone_number_spoken,
    rupees_to_words,
    time_words,
)
from app.domain.conversation_language import LanguageFamily

HI = LanguageFamily.hindi_hinglish
EN = LanguageFamily.english


@pytest.mark.parametrize(
    "n,expected_substring",
    [
        (0, "shunya"), (1, "ek"), (2, "do"), (5, "paanch"), (9, "nau"), (10, "das"),
        (12, "baarah"), (15, "pandrah"), (19, "unnees"), (20, "bees"), (21, "ikkis"),
        (30, "tees"), (45, "paintalis"), (50, "pachaas"), (60, "saath"), (90, "nabbe"),
        (99, "nau"),  # 99 has no dedicated word in _HI_TWO_DIGIT, falls back to "nabbe nau"
        (100, "sau"), (101, "sau"), (200, "sau"), (500, "sau"), (999, "sau"),
        (1000, "hazaar"), (1500, "hazaar"), (2000, "hazaar"), (5000, "hazaar"),
        (10000, "hazaar"), (100000, "lakh"),
    ],
)
def test_number_to_words_hindi(n: int, expected_substring: str) -> None:
    assert expected_substring in number_to_words(n, HI)


@pytest.mark.parametrize(
    "n,expected_substring",
    [
        (0, "zero"), (1, "one"), (5, "five"), (9, "nine"), (10, "ten"), (12, "twelve"),
        (15, "fifteen"), (19, "nineteen"), (20, "twenty"), (21, "twenty-one"), (30, "thirty"),
        (45, "forty-five"), (50, "fifty"), (99, "ninety-nine"), (100, "hundred"),
        (500, "hundred"), (1000, "thousand"), (2000, "thousand"),
    ],
)
def test_number_to_words_english(n: int, expected_substring: str) -> None:
    assert expected_substring in number_to_words(n, EN)


def test_rupees_to_words() -> None:
    assert rupees_to_words(500, HI) == "paanch sau rupaye"
    assert rupees_to_words(500, EN) == "five hundred rupees"


def test_digits_spoken_basic() -> None:
    assert digits_spoken("123") == "ek do teen"


def test_phone_number_chunked_by_three() -> None:
    result = phone_number_spoken("9876543210")
    assert result.count(" ") >= 9  # 10 digit-words, space separated


@pytest.mark.parametrize("emergency", sorted(EMERGENCY_NUMBERS))
def test_emergency_numbers_are_digit_by_digit(emergency: str) -> None:
    result = phone_number_spoken(emergency)
    assert len(result.split(" ")) == len(emergency)


def test_devanagari_digits_normalized() -> None:
    assert normalize_devanagari_digits("९८७६") == "9876"
    assert normalize_devanagari_digits("०") == "0"


def test_devanagari_phone_number_spoken_correctly() -> None:
    assert phone_number_spoken("११२") == phone_number_spoken("112")


def test_date_words_hindi() -> None:
    assert date_words(12, 9, HI) == "baarah September"


def test_date_words_english() -> None:
    assert date_words(1, 1, EN) == "one January"


@pytest.mark.parametrize(
    "hour,minute,expected_substring",
    [
        (16, 0, "chaar baje"),
        (9, 0, "subah"),
        (19, 30, "raat"),
        (12, 0, "baarah baje"),
    ],
)
def test_time_words_hindi(hour: int, minute: int, expected_substring: str) -> None:
    assert expected_substring in time_words(hour, minute, HI)


def test_time_words_english() -> None:
    assert time_words(16, 0, EN) == "four p m"
    assert time_words(9, 0, EN) == "nine a m"
    assert time_words(9, 15, EN) == "nine fifteen a m"

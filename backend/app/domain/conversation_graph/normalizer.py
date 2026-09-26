"""Speech-text normaliser (PRD v2 §9.7): turns `display_text` (what shows on screen, digits kept)
into `speech_text` (what TTS actually reads, digits spelled out) — numbers, ordinals, ₹ amounts,
dates, times, and phone/emergency numbers become words in the active language. Pure, no I/O.

Only covers realistic conversational ranges for this product (ratings 1-5, wait times, bill
amounts, phone numbers spoken digit-wise) — not a general-purpose arbitrary-precision number-to-
words library, which this domain never needs.
"""

from __future__ import annotations

import re

from app.domain.conversation_language import LanguageFamily

# Emergency numbers are always spoken digit-by-digit regardless of length (PRD §9.7) — checked
# before the general phone-number chunking rule, which groups digits instead.
EMERGENCY_NUMBERS = frozenset({"112", "108", "14416"})

_DEVANAGARI_DIGITS = "०१२३४५६७८९"
_DIGIT_TRANSLATE = str.maketrans(_DEVANAGARI_DIGITS, "0123456789")

_HI_DIGITS = ["shunya", "ek", "do", "teen", "chaar", "paanch", "chhah", "saat", "aath", "nau"]
_HI_TEENS = {
    10: "das", 11: "gyaarah", 12: "baarah", 13: "terah", 14: "chaudah", 15: "pandrah",
    16: "solah", 17: "satrah", 18: "atharah", 19: "unnees",
}
_HI_TENS = {
    20: "bees", 30: "tees", 40: "chalees", 50: "pachaas",
    60: "saath", 70: "sattar", 80: "assi", 90: "nabbe",
}
# 21-99 exceptions (Hindi tens+units aren't simply concatenated) — the common ones a demo will
# actually hit; anything not listed falls back to "<tens> <unit>" which is understandable even if
# not the single idiomatic word.
_HI_TWO_DIGIT = {
    21: "ikkis", 22: "baais", 25: "pachchees", 30: "tees", 45: "paintalis",
    50: "pachaas", 90: "nabbe", 100: "sau",
}

_EN_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen",
]
_EN_TENS = {
    20: "twenty", 30: "thirty", 40: "forty", 50: "fifty",
    60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety",
}

_HI_MONTHS = [
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
]


def normalize_devanagari_digits(text: str) -> str:
    return text.translate(_DIGIT_TRANSLATE)


def _two_digit_hi(n: int) -> str:
    if n < 10:
        return _HI_DIGITS[n]
    if n in _HI_TEENS:
        return _HI_TEENS[n]
    if n in _HI_TWO_DIGIT:
        return _HI_TWO_DIGIT[n]
    tens = (n // 10) * 10
    ones = n % 10
    if ones == 0:
        return _HI_TENS.get(tens, str(n))
    return f"{_HI_TENS.get(tens, str(tens))} {_HI_DIGITS[ones]}"


def _two_digit_en(n: int) -> str:
    if n <= 19:
        return _EN_ONES[n]
    tens = (n // 10) * 10
    ones = n % 10
    return _EN_TENS[tens] if ones == 0 else f"{_EN_TENS[tens]}-{_EN_ONES[ones]}"


def number_to_words(n: int, language: LanguageFamily) -> str:
    if n < 0:
        neg = "minus " if language == LanguageFamily.english else "minus "
        return neg + number_to_words(-n, language)
    is_hi = language == LanguageFamily.hindi_hinglish

    if n < 100:
        return _two_digit_hi(n) if is_hi else _two_digit_en(n)
    if n < 1000:
        hundreds, rem = divmod(n, 100)
        word = "sau" if is_hi else "hundred"
        head = f"{_HI_DIGITS[hundreds] if is_hi else _EN_ONES[hundreds]} {word}"
        return head if rem == 0 else f"{head} {number_to_words(rem, language)}"
    if n < 100_000:
        thousands, rem = divmod(n, 1000)
        word = "hazaar" if is_hi else "thousand"
        head = f"{number_to_words(thousands, language)} {word}"
        return head if rem == 0 else f"{head} {number_to_words(rem, language)}"
    if is_hi:
        lakhs, rem = divmod(n, 100_000)
        head = f"{number_to_words(lakhs, language)} lakh"
        return head if rem == 0 else f"{head} {number_to_words(rem, language)}"
    return str(n)  # beyond realistic conversational range in English; fall back to digits


def rupees_to_words(amount: int, language: LanguageFamily) -> str:
    words = number_to_words(amount, language)
    return f"{words} rupaye" if language == LanguageFamily.hindi_hinglish else f"{words} rupees"


def digits_spoken(digits: str, *, chunk_size: int = 3) -> str:
    """Phone/emergency numbers: spoken digit-by-digit, in 2-3 digit chunks (PRD §9.7). Digits only —
    the caller strips separators first.
    """
    words = [_HI_DIGITS[int(d)] for d in digits]
    chunks = [words[i : i + chunk_size] for i in range(0, len(words), chunk_size)]
    return " ".join(" ".join(chunk) for chunk in chunks)


def phone_number_spoken(raw: str) -> str:
    digits = re.sub(r"\D", "", normalize_devanagari_digits(raw))
    if digits in EMERGENCY_NUMBERS:
        return digits_spoken(digits, chunk_size=1)
    return digits_spoken(digits, chunk_size=3)


def date_words(day: int, month: int, language: LanguageFamily) -> str:
    day_word = number_to_words(day, language)
    return f"{day_word} {_HI_MONTHS[month - 1]}"


def time_words(hour_24: int, minute: int, language: LanguageFamily) -> str:
    period_hi = "subah" if hour_24 < 12 else "shaam" if hour_24 < 19 else "raat"
    period_en = "a m" if hour_24 < 12 else "p m"
    hour_12 = hour_24 % 12 or 12
    hour_word = number_to_words(hour_12, language)
    if language == LanguageFamily.hindi_hinglish:
        if minute == 0:
            return f"{period_hi} {hour_word} baje"
        return f"{period_hi} {hour_word} baj kar {number_to_words(minute, language)} minute"
    if minute == 0:
        return f"{hour_word} {period_en}"
    return f"{hour_word} {number_to_words(minute, language)} {period_en}"
